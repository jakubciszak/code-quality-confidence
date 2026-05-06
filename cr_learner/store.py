"""PostgreSQL + pgvector lesson store.

Handles:
* Database schema initialisation (idempotent).
* Embedding generation (Anthropic voyage-code-2 or local sentence-transformers).
* Lesson upsert with composite score calculation:
    score = authority × (1 - conflict_penalty) × time_decay × feedback_boost
* Top-K similarity search.
* Score update from feedback events.
"""
from __future__ import annotations

import logging
import math
import uuid
from datetime import UTC, datetime
from typing import Any

import psycopg2
import psycopg2.extras
from pgvector.psycopg2 import register_vector

from cr_learner.config import settings
from cr_learner.models import FeedbackEvent, Lesson, LessonRow, LessonSignals

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema DDL
# ---------------------------------------------------------------------------

_DDL = f"""
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS lessons (
    id            UUID PRIMARY KEY,
    project_id    TEXT NOT NULL,
    source_mr_iid INTEGER NOT NULL,
    source_discussion_id TEXT NOT NULL,
    domain        TEXT NOT NULL DEFAULT 'general',
    problematic_code TEXT NOT NULL DEFAULT '',
    reviewer_comment TEXT NOT NULL DEFAULT '',
    author_fix    TEXT NOT NULL DEFAULT '',
    rule_text     TEXT NOT NULL,
    score         FLOAT NOT NULL DEFAULT 0.5,
    -- signals (denormalised for fast scoring updates)
    resolved      BOOLEAN NOT NULL DEFAULT FALSE,
    code_changed_after BOOLEAN NOT NULL DEFAULT FALSE,
    award_count   INTEGER NOT NULL DEFAULT 0,
    authority_score FLOAT NOT NULL DEFAULT 0.5,
    negative_feedback INTEGER NOT NULL DEFAULT 0,
    conflict_penalty FLOAT NOT NULL DEFAULT 0.0,
    -- timestamps
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- vector
    embedding     vector({settings.embedding_dim})
);

CREATE INDEX IF NOT EXISTS lessons_embedding_idx
    ON lessons USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

CREATE INDEX IF NOT EXISTS lessons_project_idx ON lessons (project_id);
CREATE INDEX IF NOT EXISTS lessons_domain_idx  ON lessons (domain);
"""

# ---------------------------------------------------------------------------
# Embedding providers
# ---------------------------------------------------------------------------


class _AnthropicEmbedder:
    """Uses Anthropic's Voyage embeddings API."""

    def __init__(self) -> None:
        import anthropic

        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self._model = settings.embedding_model

    def embed(self, texts: list[str]) -> list[list[float]]:
        # voyage API is exposed via the anthropic client's beta namespace
        response = self._client.beta.embeddings.create(
            model=self._model,
            input=texts,
        )
        return [item.embedding for item in response.data]


class _LocalEmbedder:
    """Uses sentence-transformers for fully offline embeddings."""

    def __init__(self) -> None:
        from sentence_transformers import SentenceTransformer  # type: ignore[import]

        self._model = SentenceTransformer("all-MiniLM-L6-v2")

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self._model.encode(texts, convert_to_numpy=True).tolist()


def _build_embedder():
    if settings.embedding_provider == "local":
        return _LocalEmbedder()
    return _AnthropicEmbedder()


# ---------------------------------------------------------------------------
# Score calculation
# ---------------------------------------------------------------------------


def compute_score(signals: LessonSignals, created_at: datetime) -> float:
    """Composite lesson score in [0, 1].

    score = authority × feedback_boost × (1 - conflict_penalty) × time_decay
    """
    # Time decay: e^(-λ × days)
    now = datetime.now(UTC)
    c = created_at
    if c.tzinfo is None:
        c = c.replace(tzinfo=UTC)
    days = max(0, (now - c).days)
    decay = math.exp(-settings.time_decay_lambda * days)

    # Feedback boost from positive signals
    base = 0.5
    if signals.resolved:
        base += 0.15
    if signals.code_changed_after:
        base += 0.20
    base += min(0.10, signals.award_count * 0.02)
    base -= min(0.20, signals.negative_feedback * 0.05)
    base = max(0.0, min(1.0, base))

    score = signals.authority_score * base * (1.0 - signals.conflict_penalty) * decay
    return max(0.0, min(1.0, score))


# ---------------------------------------------------------------------------
# LessonStore
# ---------------------------------------------------------------------------


class LessonStore:
    """Manages lessons in PostgreSQL + pgvector."""

    def __init__(self, dsn: str | None = None) -> None:
        self._dsn = dsn or settings.database_url
        self._conn: psycopg2.extensions.connection | None = None
        self._embedder = _build_embedder()

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def connect(self) -> None:
        self._conn = psycopg2.connect(self._dsn)
        register_vector(self._conn)
        self._conn.autocommit = False

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> LessonStore:
        self.connect()
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def _cursor(self):
        if not self._conn:
            raise RuntimeError("LessonStore is not connected. Call connect() first.")
        return self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def init_schema(self) -> None:
        """Create tables and indexes if they don't exist."""
        with self._cursor() as cur:
            cur.execute(_DDL)
        self._conn.commit()
        logger.info("Schema initialised.")

    # ------------------------------------------------------------------
    # Embedding
    # ------------------------------------------------------------------

    def embed_lesson(self, lesson: Lesson) -> list[float]:
        """Generate an embedding for a lesson (uses rule_text + reviewer_comment)."""
        text = f"{lesson.rule_text}\n{lesson.reviewer_comment}"
        return self._embedder.embed([text])[0]

    def embed_text(self, text: str) -> list[float]:
        return self._embedder.embed([text])[0]

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def upsert(self, lesson: Lesson) -> None:
        """Insert or update a lesson (keyed by source_discussion_id + project_id)."""
        if not lesson.embedding:
            lesson.embedding = self.embed_lesson(lesson)

        lesson.score = compute_score(lesson.signals, lesson.created_at)
        lesson.updated_at = datetime.now(UTC)

        sql = """
        INSERT INTO lessons (
            id, project_id, source_mr_iid, source_discussion_id,
            domain, problematic_code, reviewer_comment, author_fix, rule_text,
            score, resolved, code_changed_after, award_count,
            authority_score, negative_feedback, conflict_penalty,
            created_at, updated_at, embedding
        ) VALUES (
            %(id)s, %(project_id)s, %(source_mr_iid)s, %(source_discussion_id)s,
            %(domain)s, %(problematic_code)s, %(reviewer_comment)s,
            %(author_fix)s, %(rule_text)s,
            %(score)s, %(resolved)s, %(code_changed_after)s, %(award_count)s,
            %(authority_score)s, %(negative_feedback)s, %(conflict_penalty)s,
            %(created_at)s, %(updated_at)s, %(embedding)s
        )
        ON CONFLICT (id) DO UPDATE SET
            domain              = EXCLUDED.domain,
            problematic_code    = EXCLUDED.problematic_code,
            reviewer_comment    = EXCLUDED.reviewer_comment,
            author_fix          = EXCLUDED.author_fix,
            rule_text           = EXCLUDED.rule_text,
            score               = EXCLUDED.score,
            resolved            = EXCLUDED.resolved,
            code_changed_after  = EXCLUDED.code_changed_after,
            award_count         = EXCLUDED.award_count,
            authority_score     = EXCLUDED.authority_score,
            negative_feedback   = EXCLUDED.negative_feedback,
            conflict_penalty    = EXCLUDED.conflict_penalty,
            updated_at          = EXCLUDED.updated_at,
            embedding           = EXCLUDED.embedding
        """
        with self._cursor() as cur:
            cur.execute(
                sql,
                {
                    "id": str(lesson.id),
                    "project_id": lesson.project_id,
                    "source_mr_iid": lesson.source_mr_iid,
                    "source_discussion_id": lesson.source_discussion_id,
                    "domain": lesson.domain,
                    "problematic_code": lesson.problematic_code,
                    "reviewer_comment": lesson.reviewer_comment,
                    "author_fix": lesson.author_fix,
                    "rule_text": lesson.rule_text,
                    "score": lesson.score,
                    "resolved": lesson.signals.resolved,
                    "code_changed_after": lesson.signals.code_changed_after,
                    "award_count": lesson.signals.award_count,
                    "authority_score": lesson.signals.authority_score,
                    "negative_feedback": lesson.signals.negative_feedback,
                    "conflict_penalty": lesson.signals.conflict_penalty,
                    "created_at": lesson.created_at,
                    "updated_at": lesson.updated_at,
                    "embedding": lesson.embedding,
                },
            )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Read / search
    # ------------------------------------------------------------------

    def search(
        self,
        query_embedding: list[float],
        top_k: int | None = None,
        domain: str | None = None,
        min_score: float = 0.0,
    ) -> list[LessonRow]:
        """Return the top-K most similar lessons by cosine similarity."""
        k = top_k or settings.retrieval_top_k
        domain_filter = "AND domain = %(domain)s" if domain else ""

        sql = f"""
        SELECT *,
               1 - (embedding <=> %(embedding)s::vector) AS similarity
        FROM lessons
        WHERE score >= %(min_score)s
          {domain_filter}
        ORDER BY embedding <=> %(embedding)s::vector
        LIMIT %(k)s
        """
        params: dict[str, Any] = {
            "embedding": query_embedding,
            "min_score": min_score,
            "k": k,
        }
        if domain:
            params["domain"] = domain

        with self._cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

        return [self._row_to_lesson_row(row) for row in rows]

    def get_by_discussion(self, project_id: str, discussion_id: str) -> Lesson | None:
        sql = "SELECT * FROM lessons WHERE project_id = %s AND source_discussion_id = %s LIMIT 1"
        with self._cursor() as cur:
            cur.execute(sql, (project_id, discussion_id))
            row = cur.fetchone()
        return self._row_to_lesson(row) if row else None

    # ------------------------------------------------------------------
    # Feedback / score update
    # ------------------------------------------------------------------

    def apply_feedback(self, event: FeedbackEvent) -> None:
        """Update a lesson's signals and recompute its score."""
        lesson = self.get_by_discussion(event.project_id, event.discussion_id)
        if not lesson:
            logger.warning(
                "No lesson found for project=%s discussion=%s",
                event.project_id,
                event.discussion_id,
            )
            return

        if event.event_type == "award":
            lesson.signals.award_count += max(0, event.value)
        elif event.event_type == "resolve":
            lesson.signals.resolved = event.value > 0
        elif event.event_type == "reply_positive":
            lesson.signals.code_changed_after = True
        elif event.event_type == "reply_negative":
            lesson.signals.negative_feedback += max(0, event.value)

        lesson.score = compute_score(lesson.signals, lesson.created_at)
        lesson.updated_at = datetime.now(UTC)

        sql = """
        UPDATE lessons
        SET score = %(score)s,
            resolved = %(resolved)s,
            code_changed_after = %(code_changed_after)s,
            award_count = %(award_count)s,
            negative_feedback = %(negative_feedback)s,
            updated_at = %(updated_at)s
        WHERE id = %(id)s
        """
        with self._cursor() as cur:
            cur.execute(
                sql,
                {
                    "id": str(lesson.id),
                    "score": lesson.score,
                    "resolved": lesson.signals.resolved,
                    "code_changed_after": lesson.signals.code_changed_after,
                    "award_count": lesson.signals.award_count,
                    "negative_feedback": lesson.signals.negative_feedback,
                    "updated_at": lesson.updated_at,
                },
            )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Private row mappers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_lesson(row: dict[str, Any]) -> Lesson:
        signals = LessonSignals(
            resolved=row["resolved"],
            code_changed_after=row["code_changed_after"],
            award_count=row["award_count"],
            authority_score=row["authority_score"],
            negative_feedback=row["negative_feedback"],
            conflict_penalty=row["conflict_penalty"],
        )
        embedding = row["embedding"]
        if hasattr(embedding, "tolist"):
            embedding = embedding.tolist()
        return Lesson(
            id=uuid.UUID(str(row["id"])),
            project_id=row["project_id"],
            source_mr_iid=row["source_mr_iid"],
            source_discussion_id=row["source_discussion_id"],
            domain=row["domain"],
            problematic_code=row["problematic_code"],
            reviewer_comment=row["reviewer_comment"],
            author_fix=row["author_fix"],
            rule_text=row["rule_text"],
            signals=signals,
            score=row["score"],
            embedding=embedding or [],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @classmethod
    def _row_to_lesson_row(cls, row: dict[str, Any]) -> LessonRow:
        return LessonRow(lesson=cls._row_to_lesson(row), similarity=float(row["similarity"]))
