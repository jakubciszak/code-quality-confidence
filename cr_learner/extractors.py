"""GitLab MR extractor and LLM-based lesson extractor.

Responsibilities
----------------
* Pull MR data (diff, discussions, versions, approvals) from the GitLab REST API.
* For each discussion, detect whether the author changed code after the comment
  (by comparing MR versions before/after the comment timestamp).
* Use an LLM (Claude) to extract a structured "lesson" from each resolved
  or code-changing discussion.
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

import anthropic
import gitlab
from tenacity import retry, stop_after_attempt, wait_exponential

from cr_learner.config import settings
from cr_learner.models import (
    DiffVersion,
    Discussion,
    DiscussionNote,
    Lesson,
    LessonSignals,
    MRData,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# GitLab client helpers
# ---------------------------------------------------------------------------


def _get_gitlab_client() -> gitlab.Gitlab:
    gl = gitlab.Gitlab(settings.gitlab_url, private_token=settings.gitlab_token)
    gl.auth()
    return gl


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# ---------------------------------------------------------------------------
# MR data extractor
# ---------------------------------------------------------------------------


class MRExtractor:
    """Extracts all relevant data for a GitLab Merge Request."""

    def __init__(self, project_id: str | None = None) -> None:
        self._project_id = project_id or settings.gitlab_project_id
        self._gl = _get_gitlab_client()
        self._project = self._gl.projects.get(self._project_id)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract(self, mr_iid: int) -> MRData:
        """Return a fully populated :class:`MRData` for the given MR IID."""
        mr = self._project.mergerequests.get(mr_iid)

        diff = self._get_diff(mr)
        discussions = self._get_discussions(mr)
        versions = self._get_versions(mr)
        approvals = self._get_approvals(mr)
        pipeline_status = self._get_pipeline_status(mr)

        return MRData(
            mr_id=mr.id,
            mr_iid=mr.iid,
            project_id=str(self._project_id),
            title=mr.title,
            description=mr.description or "",
            state=mr.state,
            target_branch=mr.target_branch,
            source_branch=mr.source_branch,
            author_username=mr.author["username"],
            created_at=_parse_dt(mr.created_at) or datetime.now(UTC),
            merged_at=_parse_dt(getattr(mr, "merged_at", None)),
            labels=mr.labels or [],
            diff=diff,
            discussions=discussions,
            versions=versions,
            approvals=approvals,
            pipeline_status=pipeline_status,
            related_issues=self._get_related_issues(mr),
        )

    def list_merged_mr_iids(self, limit: int = 100) -> list[int]:
        """Return IIDs of the most recent *merged* MRs (up to *limit*)."""
        mrs = self._project.mergerequests.list(
            state="merged", order_by="updated_at", sort="desc", per_page=limit
        )
        return [mr.iid for mr in mrs]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_diff(self, mr) -> str:
        """Return the unified diff string for the whole MR."""
        try:
            diffs = mr.diffs.list(get_all=True)
            if not diffs:
                return ""
            # Use the latest version's diff
            latest = sorted(diffs, key=lambda d: d.id, reverse=True)[0]
            changes = latest.diffs
            parts: list[str] = []
            for change in changes:
                header = f"--- a/{change['old_path']}\n+++ b/{change['new_path']}"
                parts.append(header + "\n" + change.get("diff", ""))
            return "\n".join(parts)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not fetch diff for MR !%s: %s", mr.iid, exc)
            return ""

    def _get_discussions(self, mr) -> list[Discussion]:
        raw_discussions = mr.discussions.list(get_all=True)
        result: list[Discussion] = []
        for d in raw_discussions:
            notes = [
                DiscussionNote(
                    id=n["id"],
                    author_username=n["author"]["username"],
                    author_name=n["author"]["name"],
                    body=n["body"],
                    created_at=_parse_dt(n["created_at"]) or datetime.now(UTC),
                    updated_at=_parse_dt(n["updated_at"]) or datetime.now(UTC),
                    resolved=n.get("resolved", False),
                    position=n.get("position"),
                )
                for n in d.attributes.get("notes", [])
            ]
            if not notes:
                continue
            result.append(
                Discussion(
                    id=d.id,
                    notes=notes,
                    resolved=d.attributes.get("resolved", False),
                    resolvable=d.attributes.get("resolvable", False),
                )
            )
        return result

    def _get_versions(self, mr) -> list[DiffVersion]:
        try:
            raw = mr.diffs.list(get_all=True)
            return [
                DiffVersion(
                    id=v.id,
                    head_sha=v.head_commit_sha,
                    base_commit_sha=v.base_commit_sha,
                    start_commit_sha=v.start_commit_sha,
                    created_at=_parse_dt(v.created_at) or datetime.now(UTC),
                    state=v.state,
                    real_size=getattr(v, "real_size", None),
                )
                for v in raw
            ]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not fetch versions for MR !%s: %s", mr.iid, exc)
            return []

    def _get_approvals(self, mr) -> list[str]:
        try:
            approvals = mr.approvals.get()
            return [a["user"]["username"] for a in approvals.approved_by or []]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not fetch approvals for MR !%s: %s", mr.iid, exc)
            return []

    def _get_pipeline_status(self, mr) -> str | None:
        try:
            pipelines = mr.pipelines.list()
            if pipelines:
                return pipelines[0].status
        except Exception:  # noqa: BLE001
            pass
        return None

    def _get_related_issues(self, mr) -> list[int]:
        try:
            refs = mr.closes_issues()
            return [issue.iid for issue in refs]
        except Exception:  # noqa: BLE001
            return []


# ---------------------------------------------------------------------------
# Code-change detection
# ---------------------------------------------------------------------------


def code_changed_after_comment(
    comment_time: datetime,
    versions: list[DiffVersion],
) -> bool:
    """Return True if a new MR version was created *after* the comment."""
    for v in versions:
        v_time = v.created_at
        if v_time.tzinfo is None:
            v_time = v_time.replace(tzinfo=UTC)
        c_time = comment_time
        if c_time.tzinfo is None:
            c_time = c_time.replace(tzinfo=UTC)
        if v_time > c_time:
            return True
    return False


# ---------------------------------------------------------------------------
# LLM-based lesson extractor
# ---------------------------------------------------------------------------

_LESSON_SYSTEM_PROMPT = """\
You are a senior code-review analyst. Given a merge-request discussion thread,
extract a reusable code-review lesson in JSON.

Return ONLY valid JSON with the following keys:
{
  "domain": "<tech domain, e.g. python, kafka, postgresql, general>",
  "problematic_code": "<short code snippet or pattern that was problematic, or empty string>",
  "reviewer_comment": "<the core feedback from the reviewer, ≤ 3 sentences>",
  "author_fix": "<what the author changed in response, or empty string>",
  "rule_text": "<one actionable rule derived from this discussion, ≤ 2 sentences>"
}
If you cannot extract a meaningful lesson, return {"rule_text": ""} and nothing else.
"""


class LessonExtractor:
    """Uses an LLM to turn an MR discussion into a structured :class:`Lesson`."""

    def __init__(self) -> None:
        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10))
    def extract(self, mr_data: MRData, discussion: Discussion) -> Lesson | None:
        """Return a :class:`Lesson` or *None* if the discussion is not instructive."""
        thread_text = self._format_thread(discussion)
        if not thread_text.strip():
            return None

        code_changed = code_changed_after_comment(
            discussion.notes[0].created_at if discussion.notes else datetime.now(UTC),
            mr_data.versions,
        )

        context = (
            f"MR title: {mr_data.title}\n"
            f"Target branch: {mr_data.target_branch}\n"
            f"Labels: {', '.join(mr_data.labels) or 'none'}\n\n"
            f"Discussion thread:\n{thread_text}"
        )

        message = self._client.messages.create(
            model=settings.llm_model,
            max_tokens=512,
            system=_LESSON_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": context}],
        )

        raw = message.content[0].text.strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("LLM returned non-JSON: %s", raw[:200])
            return None

        rule_text = data.get("rule_text", "").strip()
        if not rule_text:
            return None

        # Determine reviewer authority based on approvals list
        reviewer = discussion.notes[0].author_username if discussion.notes else ""
        authority = 0.7 if reviewer in mr_data.approvals else 0.5

        signals = LessonSignals(
            resolved=discussion.resolved,
            code_changed_after=code_changed,
            award_count=0,
            authority_score=authority,
        )

        return Lesson(
            project_id=mr_data.project_id,
            source_mr_iid=mr_data.mr_iid,
            source_discussion_id=discussion.id,
            domain=data.get("domain", "general"),
            problematic_code=data.get("problematic_code", ""),
            reviewer_comment=data.get("reviewer_comment", ""),
            author_fix=data.get("author_fix", ""),
            rule_text=rule_text,
            signals=signals,
        )

    @staticmethod
    def _format_thread(discussion: Discussion) -> str:
        lines: list[str] = []
        for note in discussion.notes:
            lines.append(f"[{note.author_username}]: {note.body}")
        return "\n".join(lines)
