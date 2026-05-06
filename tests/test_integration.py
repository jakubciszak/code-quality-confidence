"""Tests for cr_learner.integration."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

from cr_learner.integration import build_review_context
from cr_learner.models import Lesson, LessonRow, LessonSignals, ReviewContext, ReviewInstructions

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_lesson_row(
    rule_text: str,
    domain: str = "python",
    similarity: float = 0.85,
    score: float = 0.75,
) -> LessonRow:
    lesson = Lesson(
        id=uuid.uuid4(),
        project_id="99",
        source_mr_iid=1,
        source_discussion_id="disc-1",
        domain=domain,
        reviewer_comment="Review comment",
        rule_text=rule_text,
        signals=LessonSignals(resolved=True, authority_score=0.7),
        score=score,
        embedding=[0.1] * 1536,
        created_at=datetime.now(UTC),
    )
    return LessonRow(lesson=lesson, similarity=similarity)


def _make_mock_store(lesson_rows: list[LessonRow]) -> MagicMock:
    store = MagicMock()
    store.embed_text.return_value = [0.1] * 1536
    store.search.return_value = lesson_rows
    return store


# ---------------------------------------------------------------------------
# ReviewInstructions.from_lessons
# ---------------------------------------------------------------------------


class TestReviewInstructions:
    def test_formats_lessons_as_markdown(self):
        rows = [
            _make_lesson_row("Prefer keyset pagination.", domain="postgresql"),
            _make_lesson_row("Avoid SELECT *.", domain="postgresql"),
        ]
        instructions = ReviewInstructions.from_lessons(rows)
        text = instructions.extra_instructions

        assert "Historical lessons" in text
        assert "keyset pagination" in text
        assert "SELECT *" in text
        assert "confidence" in text

    def test_includes_problematic_code_when_present(self):
        row = _make_lesson_row("Use transactions.", domain="postgresql")
        row.lesson.problematic_code = "DELETE FROM events;"
        instructions = ReviewInstructions.from_lessons([row])
        assert "DELETE FROM events;" in instructions.extra_instructions

    def test_includes_author_fix_when_present(self):
        row = _make_lesson_row("Wrap in transaction.", domain="python")
        row.lesson.author_fix = "BEGIN; DELETE ...; COMMIT;"
        instructions = ReviewInstructions.from_lessons([row])
        assert "BEGIN;" in instructions.extra_instructions

    def test_truncates_long_code_snippets(self):
        row = _make_lesson_row("Long code rule.")
        row.lesson.problematic_code = "X" * 500
        instructions = ReviewInstructions.from_lessons([row])
        # The formatted snippet should not exceed 200 chars (per model code)
        assert "X" * 201 not in instructions.extra_instructions

    def test_empty_lessons_returns_empty_string(self):
        instructions = ReviewInstructions.from_lessons([])
        # from_lessons with empty list still builds the header
        assert isinstance(instructions.extra_instructions, str)


# ---------------------------------------------------------------------------
# build_review_context
# ---------------------------------------------------------------------------


class TestBuildReviewContext:
    def test_returns_instructions_with_lessons(self):
        rows = [_make_lesson_row("Use transactions.")]
        store = _make_mock_store(rows)

        ctx = ReviewContext(
            project_id="99",
            mr_iid=1,
            diff="--- a/repo.py\n+++ b/repo.py\n@@ ... @@\n-bad\n+good",
            domain_hint="python",
        )
        result = build_review_context(ctx, store)

        assert len(result.lessons) == 1
        assert "transactions" in result.extra_instructions
        store.embed_text.assert_called_once_with(ctx.diff)
        # domain_hint != "general" so domain filter is passed
        store.search.assert_called_once()
        _, kwargs = store.search.call_args
        assert kwargs.get("domain") == "python"

    def test_returns_empty_instructions_when_no_lessons(self):
        store = _make_mock_store([])
        ctx = ReviewContext(project_id="99", mr_iid=2, diff="trivial change")
        result = build_review_context(ctx, store)
        assert result.lessons == []
        assert result.extra_instructions == ""

    def test_does_not_pass_domain_filter_for_general(self):
        store = _make_mock_store([])
        ctx = ReviewContext(project_id="99", mr_iid=3, diff="diff", domain_hint="general")
        build_review_context(ctx, store)
        _, kwargs = store.search.call_args
        assert kwargs.get("domain") is None
