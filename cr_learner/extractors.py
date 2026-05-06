"""PR data extractors and LLM-based lesson extractor.

Supported platforms
-------------------
* **GitLab** — via ``python-gitlab`` (REST API).
* **GitHub** — via ``PyGithub`` (REST API).

Both extractors implement the :class:`PRExtractor` abstract base class and
produce the same :class:`~cr_learner.models.MRData` structure so all
downstream components remain platform-agnostic.

Use :func:`get_extractor` to obtain the right extractor for the active platform.
"""
from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from datetime import UTC, datetime

import anthropic
import gitlab
from github import Auth, Github
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
# Shared helpers
# ---------------------------------------------------------------------------


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def code_changed_after_comment(
    comment_time: datetime,
    versions: list[DiffVersion],
) -> bool:
    """Return True if a new PR version was created *after* the comment."""
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
# Abstract base
# ---------------------------------------------------------------------------


class PRExtractor(ABC):
    """Platform-agnostic interface for extracting PR/MR data."""

    @abstractmethod
    def extract(self, pr_number: int) -> MRData:
        """Return a fully populated :class:`MRData` for the given PR/MR number."""

    @abstractmethod
    def list_merged_pr_numbers(self, limit: int = 100) -> list[int]:
        """Return PR/MR numbers of the *limit* most recently merged PRs."""


# ---------------------------------------------------------------------------
# GitLab extractor
# ---------------------------------------------------------------------------


def _get_gitlab_client() -> gitlab.Gitlab:
    gl = gitlab.Gitlab(settings.gitlab_url, private_token=settings.gitlab_token)
    gl.auth()
    return gl


class GitLabExtractor(PRExtractor):
    """Extracts all relevant data for a GitLab Merge Request."""

    def __init__(self, project_id: str | None = None) -> None:
        self._project_id = project_id or settings.gitlab_project_id
        self._gl = _get_gitlab_client()
        self._project = self._gl.projects.get(self._project_id)

    def extract(self, pr_number: int) -> MRData:
        mr = self._project.mergerequests.get(pr_number)

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
            platform="gitlab",
        )

    def list_merged_pr_numbers(self, limit: int = 100) -> list[int]:
        mrs = self._project.mergerequests.list(
            state="merged", order_by="updated_at", sort="desc", per_page=limit
        )
        return [mr.iid for mr in mrs]

    # Keep legacy name for backward-compat
    def list_merged_mr_iids(self, limit: int = 100) -> list[int]:
        return self.list_merged_pr_numbers(limit)

    def _get_diff(self, mr) -> str:
        try:
            diffs = mr.diffs.list(get_all=True)
            if not diffs:
                return ""
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


# Backward-compatible alias
MRExtractor = GitLabExtractor


# ---------------------------------------------------------------------------
# GitHub extractor
# ---------------------------------------------------------------------------


class GitHubExtractor(PRExtractor):
    """Extracts all relevant data for a GitHub Pull Request.

    The extracted data is mapped to the same :class:`~cr_learner.models.MRData`
    model used by :class:`GitLabExtractor` so downstream components stay
    platform-agnostic.

    Field mapping
    ~~~~~~~~~~~~~
    * ``mr_id``      ← PR node ID (numeric hash)
    * ``mr_iid``     ← PR number
    * ``project_id`` ← ``"owner/repo"``
    * ``versions``   ← PR commits (each commit = one "version")
    * ``approvals``  ← usernames who submitted an approving review
    """

    def __init__(self, repo: str | None = None) -> None:
        """
        Parameters
        ----------
        repo:
            GitHub repository in ``"owner/repo"`` format.
            Falls back to :attr:`~cr_learner.config.Settings.github_repo`.
        """
        self._repo_name = repo or settings.github_repo
        auth = Auth.Token(settings.github_token)
        base_url = settings.github_url
        if base_url and base_url != "https://api.github.com":
            # GitHub Enterprise Server
            self._gh = Github(base_url=base_url, auth=auth)
        else:
            self._gh = Github(auth=auth)
        self._repo = self._gh.get_repo(self._repo_name)

    def extract(self, pr_number: int) -> MRData:
        pr = self._repo.get_pull(pr_number)

        diff = self._get_diff(pr)
        discussions = self._get_discussions(pr)
        versions = self._get_versions(pr)
        approvals = self._get_approvals(pr)
        pipeline_status = self._get_pipeline_status(pr)

        return MRData(
            # GitHub exposes an internal node_id and a numeric id; we use
            # pr.number for both fields here so callers can use mr_iid as the
            # familiar PR number for display / linking purposes.
            mr_id=pr.number,
            mr_iid=pr.number,
            project_id=self._repo_name,
            title=pr.title,
            description=pr.body or "",
            state=pr.state,
            target_branch=pr.base.ref,
            source_branch=pr.head.ref,
            author_username=pr.user.login,
            created_at=pr.created_at.replace(tzinfo=UTC) if pr.created_at.tzinfo is None
            else pr.created_at,
            merged_at=pr.merged_at,
            labels=[label.name for label in pr.labels],
            diff=diff,
            discussions=discussions,
            versions=versions,
            approvals=approvals,
            pipeline_status=pipeline_status,
            related_issues=[],
            platform="github",
        )

    def list_merged_pr_numbers(self, limit: int = 100) -> list[int]:
        pulls = self._repo.get_pulls(state="closed", sort="updated", direction="desc")
        result: list[int] = []
        for pr in pulls:
            if pr.merged_at is not None:
                result.append(pr.number)
            if len(result) >= limit:
                break
        return result

    def _get_diff(self, pr) -> str:
        """Build a unified diff string from the list of changed files."""
        try:
            parts: list[str] = []
            for f in pr.get_files():
                header = f"--- a/{f.filename}\n+++ b/{f.filename}"
                patch = f.patch or ""
                parts.append(header + "\n" + patch)
            return "\n".join(parts)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not fetch diff for PR #%s: %s", pr.number, exc)
            return ""

    def _get_discussions(self, pr) -> list[Discussion]:
        """Convert GitHub review comments and issue comments into Discussions.

        Each inline review comment thread is mapped to a Discussion whose
        ``id`` is the comment's ``in_reply_to_id`` (or its own ``id`` if it
        is the root of a thread).  General issue comments each become their
        own single-note Discussion.
        """
        result: list[Discussion] = []

        # --- Inline review-comment threads ---
        threads: dict[int, list[DiscussionNote]] = {}
        try:
            for comment in pr.get_review_comments():
                root_id = comment.in_reply_to_id or comment.id
                note = DiscussionNote(
                    id=comment.id,
                    author_username=comment.user.login,
                    author_name=comment.user.name or comment.user.login,
                    body=comment.body,
                    created_at=comment.created_at.replace(tzinfo=UTC)
                    if comment.created_at.tzinfo is None
                    else comment.created_at,
                    updated_at=comment.updated_at.replace(tzinfo=UTC)
                    if comment.updated_at.tzinfo is None
                    else comment.updated_at,
                    resolved=False,  # GitHub doesn't expose resolved per-comment
                    position={"path": comment.path, "line": comment.line},
                )
                threads.setdefault(root_id, []).append(note)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not fetch review comments for PR #%s: %s", pr.number, exc)

        for thread_id, notes in threads.items():
            result.append(
                Discussion(
                    id=str(thread_id),
                    notes=notes,
                    resolved=False,
                    resolvable=True,
                )
            )

        # --- General issue comments ---
        try:
            for comment in pr.get_issue_comments():
                note = DiscussionNote(
                    id=comment.id,
                    author_username=comment.user.login,
                    author_name=comment.user.name or comment.user.login,
                    body=comment.body,
                    created_at=comment.created_at.replace(tzinfo=UTC)
                    if comment.created_at.tzinfo is None
                    else comment.created_at,
                    updated_at=comment.updated_at.replace(tzinfo=UTC)
                    if comment.updated_at.tzinfo is None
                    else comment.updated_at,
                    resolved=False,
                )
                result.append(
                    Discussion(
                        id=str(comment.id),
                        notes=[note],
                        resolved=False,
                        resolvable=False,
                    )
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not fetch issue comments for PR #%s: %s", pr.number, exc)

        return result

    def _get_versions(self, pr) -> list[DiffVersion]:
        """Map each PR commit to a :class:`DiffVersion`."""
        try:
            return [
                DiffVersion(
                    id=i + 1,
                    head_sha=commit.sha,
                    base_commit_sha=commit.parents[0].sha if commit.parents else "",
                    start_commit_sha=commit.parents[0].sha if commit.parents else "",
                    created_at=commit.commit.author.date.replace(tzinfo=UTC)
                    if commit.commit.author.date.tzinfo is None
                    else commit.commit.author.date,
                    state="collected",
                )
                for i, commit in enumerate(pr.get_commits())
            ]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not fetch commits for PR #%s: %s", pr.number, exc)
            return []

    def _get_approvals(self, pr) -> list[str]:
        """Return usernames of reviewers who submitted an approving review."""
        try:
            return [
                review.user.login
                for review in pr.get_reviews()
                if review.state == "APPROVED"
            ]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not fetch reviews for PR #%s: %s", pr.number, exc)
            return []

    def _get_pipeline_status(self, pr) -> str | None:
        """Return the combined commit status for the PR head."""
        try:
            combined = self._repo.get_commit(pr.head.sha).get_combined_status()
            return combined.state  # "success", "failure", "pending", "error"
        except Exception:  # noqa: BLE001
            return None


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def get_extractor(
    platform: str | None = None,
    project_id: str | None = None,
) -> PRExtractor:
    """Return the correct :class:`PRExtractor` for the given *platform*.

    Parameters
    ----------
    platform:
        ``"gitlab"`` or ``"github"``.  Defaults to
        :attr:`~cr_learner.config.Settings.platform`.
    project_id:
        GitLab project ID **or** GitHub ``"owner/repo"`` slug.  If omitted,
        the value from config is used.
    """
    p = (platform or settings.platform).lower()
    if p == "github":
        return GitHubExtractor(repo=project_id)
    if p == "gitlab":
        return GitLabExtractor(project_id=project_id)
    raise ValueError(f"Unknown platform: {p!r}. Choose 'gitlab' or 'github'.")


# ---------------------------------------------------------------------------
# LLM-based lesson extractor (platform-agnostic)
# ---------------------------------------------------------------------------

_LESSON_SYSTEM_PROMPT = """\
You are a senior code-review analyst. Given a pull-request discussion thread,
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
    """Uses an LLM to turn a PR discussion into a structured :class:`Lesson`."""

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
            f"PR title: {mr_data.title}\n"
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
