"""Pydantic data models shared across cr-learner components."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# GitLab raw data
# ---------------------------------------------------------------------------


class DiffVersion(BaseModel):
    """One version (snapshot) of an MR diff."""

    id: int
    head_sha: str
    base_commit_sha: str
    start_commit_sha: str
    created_at: datetime
    state: str
    real_size: str | None = None


class DiscussionNote(BaseModel):
    """A single note (comment) inside a discussion thread."""

    id: int
    author_username: str
    author_name: str
    body: str
    created_at: datetime
    updated_at: datetime
    resolved: bool = False
    position: dict[str, Any] | None = None  # inline position if any


class Discussion(BaseModel):
    """A discussion thread on an MR (may be inline or general)."""

    id: str
    notes: list[DiscussionNote]
    resolved: bool = False
    resolvable: bool = False

    @property
    def first_note(self) -> DiscussionNote | None:
        return self.notes[0] if self.notes else None

    @property
    def replies(self) -> list[DiscussionNote]:
        return self.notes[1:]


class MRData(BaseModel):
    """All data extracted for a single Merge Request."""

    mr_id: int
    mr_iid: int
    project_id: str
    title: str
    description: str = ""
    state: str
    target_branch: str
    source_branch: str
    author_username: str
    created_at: datetime
    merged_at: datetime | None = None
    labels: list[str] = Field(default_factory=list)
    diff: str = ""  # unified diff of the whole MR
    discussions: list[Discussion] = Field(default_factory=list)
    versions: list[DiffVersion] = Field(default_factory=list)
    approvals: list[str] = Field(default_factory=list)  # usernames who approved
    pipeline_status: str | None = None
    related_issues: list[int] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Lessons
# ---------------------------------------------------------------------------


class LessonSignals(BaseModel):
    """Six feedback signals used to score a lesson."""

    resolved: bool = False
    code_changed_after: bool = False
    award_count: int = 0  # 👍 reactions on the original comment
    authority_score: float = 0.5  # reviewer authority in the lesson's domain
    negative_feedback: int = 0  # bot comment ignored / downvoted
    conflict_penalty: float = 0.0  # reduced if a senior contradicts this lesson


class Lesson(BaseModel):
    """A structured lesson extracted from an MR discussion."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    project_id: str
    source_mr_iid: int
    source_discussion_id: str
    domain: str = "general"  # e.g. "kafka", "postgresql", "python"
    problematic_code: str = ""
    reviewer_comment: str
    author_fix: str = ""
    rule_text: str  # the human-readable rule / lesson summary
    signals: LessonSignals = Field(default_factory=LessonSignals)
    score: float = 0.5  # composite score in [0, 1]
    embedding: list[float] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class LessonRow(BaseModel):
    """Database row returned by a similarity search."""

    lesson: Lesson
    similarity: float  # cosine similarity in [0, 1]


# ---------------------------------------------------------------------------
# PR-Agent integration
# ---------------------------------------------------------------------------


class ReviewContext(BaseModel):
    """Input for the integration hook."""

    project_id: str
    mr_iid: int
    diff: str
    domain_hint: str = "general"


class ReviewInstructions(BaseModel):
    """Output of the integration hook — fed to PR-Agent as extra_instructions."""

    lessons: list[LessonRow]
    extra_instructions: str

    @classmethod
    def from_lessons(cls, lessons: list[LessonRow]) -> ReviewInstructions:
        lines: list[str] = [
            "## Historical lessons from past code reviews\n",
            "Apply the following lessons when reviewing this MR:\n",
        ]
        for i, row in enumerate(lessons, 1):
            lesson = row.lesson
            lines.append(
                f"{i}. **[{lesson.domain}]** {lesson.rule_text}"
                f" *(confidence: {lesson.score:.2f})*"
            )
            if lesson.problematic_code:
                lines.append(f"   - Bad pattern: `{lesson.problematic_code[:200]}`")
            if lesson.author_fix:
                lines.append(f"   - Preferred fix: `{lesson.author_fix[:200]}`")
        return cls(lessons=lessons, extra_instructions="\n".join(lines))


# ---------------------------------------------------------------------------
# Feedback webhook
# ---------------------------------------------------------------------------


class FeedbackEvent(BaseModel):
    """Parsed GitLab webhook event that affects lesson scores."""

    project_id: str
    discussion_id: str
    event_type: str  # "award", "resolve", "reply_positive", "reply_negative"
    value: int = 1  # +1 or -1
