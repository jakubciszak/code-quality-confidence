"""Tests for cr_learner.store — scoring, embedder interfaces and LessonStore logic."""
from __future__ import annotations

import math
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from cr_learner.models import FeedbackEvent, Lesson, LessonSignals
from cr_learner.store import LessonStore, compute_score

# ---------------------------------------------------------------------------
# compute_score
# ---------------------------------------------------------------------------


class TestComputeScore:
    def _make_signals(self, **kwargs) -> LessonSignals:
        defaults = dict(
            resolved=False,
            code_changed_after=False,
            award_count=0,
            authority_score=0.5,
            negative_feedback=0,
            conflict_penalty=0.0,
        )
        defaults.update(kwargs)
        return LessonSignals(**defaults)

    def _recent(self) -> datetime:
        return datetime.now(UTC) - timedelta(days=1)

    def test_score_in_zero_one(self):
        signals = self._make_signals()
        score = compute_score(signals, self._recent())
        assert 0.0 <= score <= 1.0

    def test_resolved_increases_score(self):
        base_signals = self._make_signals(resolved=False)
        resolved_signals = self._make_signals(resolved=True)
        ts = self._recent()
        assert compute_score(resolved_signals, ts) > compute_score(base_signals, ts)

    def test_code_changed_increases_score(self):
        base_signals = self._make_signals()
        changed_signals = self._make_signals(code_changed_after=True)
        ts = self._recent()
        assert compute_score(changed_signals, ts) > compute_score(base_signals, ts)

    def test_negative_feedback_decreases_score(self):
        base_signals = self._make_signals()
        neg_signals = self._make_signals(negative_feedback=3)
        ts = self._recent()
        assert compute_score(neg_signals, ts) < compute_score(base_signals, ts)

    def test_old_lesson_has_lower_score(self):
        signals = self._make_signals(resolved=True, code_changed_after=True)
        recent_ts = self._recent()
        old_ts = datetime.now(UTC) - timedelta(days=365)
        assert compute_score(signals, recent_ts) > compute_score(signals, old_ts)

    def test_conflict_penalty_reduces_score(self):
        no_conflict = self._make_signals()
        with_conflict = self._make_signals(conflict_penalty=0.5)
        ts = self._recent()
        assert compute_score(with_conflict, ts) < compute_score(no_conflict, ts)

    def test_high_authority_increases_score(self):
        low_auth = self._make_signals(authority_score=0.1)
        high_auth = self._make_signals(authority_score=0.9)
        ts = self._recent()
        assert compute_score(high_auth, ts) > compute_score(low_auth, ts)

    def test_time_decay_formula(self):
        """Check that decay matches exp(-λ * days) formula."""
        from cr_learner.config import settings

        signals = LessonSignals(authority_score=1.0, resolved=True, code_changed_after=True)
        days = 100
        ts = datetime.now(UTC) - timedelta(days=days)
        score = compute_score(signals, ts)
        expected_decay = math.exp(-settings.time_decay_lambda * days)
        # score should be proportional to decay; verify it's within 1% of expected ratio
        max_score_no_decay = compute_score(signals, datetime.now(UTC) - timedelta(days=1))
        ratio = score / (max_score_no_decay + 1e-9)
        decay_ratio = expected_decay / math.exp(-settings.time_decay_lambda * 1)
        assert abs(ratio - decay_ratio) < 0.02


# ---------------------------------------------------------------------------
# LessonStore (unit — uses a mock psycopg2 connection)
# ---------------------------------------------------------------------------


def _make_lesson(project_id: str = "99", discussion_id: str = "disc-1") -> Lesson:
    return Lesson(
        id=uuid.uuid4(),
        project_id=project_id,
        source_mr_iid=1,
        source_discussion_id=discussion_id,
        domain="python",
        reviewer_comment="Use keyset pagination.",
        rule_text="Prefer keyset pagination over OFFSET.",
        signals=LessonSignals(
            resolved=True,
            code_changed_after=True,
            authority_score=0.7,
        ),
        embedding=[0.1] * 1536,
        created_at=datetime.now(UTC),
    )


class TestLessonStoreUnit:
    """Unit tests for LessonStore methods that don't need a real DB."""

    def _make_store_with_mock_conn(self):
        """Return a LessonStore with a mocked psycopg2 connection."""
        store = LessonStore.__new__(LessonStore)
        store._dsn = "mock"
        store._embedder = MagicMock()
        store._embedder.embed.return_value = [[0.1] * 1536]

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        store._conn = mock_conn
        return store, mock_conn, mock_cursor

    def test_embed_lesson_calls_embedder(self):
        store, _, _ = self._make_store_with_mock_conn()
        lesson = _make_lesson()
        embedding = store.embed_lesson(lesson)
        assert len(embedding) == 1536
        store._embedder.embed.assert_called_once()

    def test_upsert_computes_score(self):
        store, mock_conn, mock_cursor = self._make_store_with_mock_conn()
        lesson = _make_lesson()
        lesson.embedding = [0.1] * 1536  # pre-set so embedder not called

        store.upsert(lesson)

        assert 0.0 <= lesson.score <= 1.0
        mock_conn.commit.assert_called_once()

    def test_apply_feedback_award(self):
        store, mock_conn, mock_cursor = self._make_store_with_mock_conn()
        lesson = _make_lesson()

        # Patch get_by_discussion to return the lesson
        store.get_by_discussion = MagicMock(return_value=lesson)

        event = FeedbackEvent(
            project_id="99",
            discussion_id="disc-1",
            event_type="award",
            value=1,
        )
        store.apply_feedback(event)

        assert lesson.signals.award_count == 1
        mock_conn.commit.assert_called_once()

    def test_apply_feedback_resolve(self):
        store, _, _ = self._make_store_with_mock_conn()
        lesson = _make_lesson()
        lesson.signals.resolved = False
        store.get_by_discussion = MagicMock(return_value=lesson)

        event = FeedbackEvent(
            project_id="99",
            discussion_id="disc-1",
            event_type="resolve",
            value=1,
        )
        store.apply_feedback(event)
        assert lesson.signals.resolved is True

    def test_apply_feedback_reply_negative(self):
        store, _, _ = self._make_store_with_mock_conn()
        lesson = _make_lesson()
        lesson.signals.negative_feedback = 0
        store.get_by_discussion = MagicMock(return_value=lesson)

        event = FeedbackEvent(
            project_id="99",
            discussion_id="disc-1",
            event_type="reply_negative",
            value=1,
        )
        store.apply_feedback(event)
        assert lesson.signals.negative_feedback == 1

    def test_apply_feedback_logs_warning_when_no_lesson(self, caplog):
        import logging

        store, _, _ = self._make_store_with_mock_conn()
        store.get_by_discussion = MagicMock(return_value=None)

        event = FeedbackEvent(
            project_id="99",
            discussion_id="nonexistent",
            event_type="award",
            value=1,
        )
        with caplog.at_level(logging.WARNING, logger="cr_learner.store"):
            store.apply_feedback(event)
        assert "No lesson found" in caplog.text
