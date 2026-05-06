"""Webhook receiver for the feedback loop — supports GitLab and GitHub.

GitLab events handled
---------------------
* ``Emoji Hook``          → award (+1) or unaward (−1) on a note
* ``Note Hook``           → reply to a bot comment, analysed for sentiment
* ``Merge Request Hook``  → detect resolved discussions

GitHub events handled
---------------------
* ``pull_request_review``         → approved review → resolve (+)
* ``pull_request_review_comment`` → inline comment reply, analysed for sentiment
* ``issue_comment``               → general PR comment, analysed for sentiment
* ``reaction`` (create/delete)    → 👍 award / unaward on a comment

Run with::

    cr-learner serve

or directly::

    uvicorn cr_learner.feedback:app --host 0.0.0.0 --port 8080
"""
from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request, status

from cr_learner.config import settings
from cr_learner.models import FeedbackEvent
from cr_learner.store import LessonStore

logger = logging.getLogger(__name__)

app = FastAPI(title="cr-learner feedback webhook", version="0.1.0")

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_POSITIVE_KW = {"lgtm", "fixed", "done", "thanks", "good catch", "applied", "resolved"}
_NEGATIVE_KW = {"disagree", "no", "won't fix", "wontfix", "not applicable", "false positive"}


def _sentiment(body: str) -> str | None:
    """Return 'reply_positive', 'reply_negative', or None."""
    text = body.lower()
    if any(kw in text for kw in _POSITIVE_KW):
        return "reply_positive"
    if any(kw in text for kw in _NEGATIVE_KW):
        return "reply_negative"
    return None


# ---------------------------------------------------------------------------
# Webhook signature verification
# ---------------------------------------------------------------------------


def _verify_gitlab_token(token: str | None) -> None:
    """Verify the GitLab webhook secret token."""
    expected = settings.webhook_secret
    if not expected:
        return
    if token != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


def _verify_github_signature(body: bytes, signature: str | None) -> None:
    """Verify the GitHub ``X-Hub-Signature-256`` HMAC."""
    secret = settings.webhook_secret
    if not secret:
        return
    if not signature or not signature.startswith("sha256="):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing signature")
    expected = "sha256=" + hmac.new(
        secret.encode(), body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")


# ---------------------------------------------------------------------------
# GitLab event handlers
# ---------------------------------------------------------------------------


def _gitlab_handle_award(payload: dict[str, Any]) -> FeedbackEvent | None:
    award = payload.get("object_attributes", {})
    project = payload.get("project", {})
    project_id = str(project.get("id", ""))

    if award.get("awardable_type") != "Note":
        return None

    note_id = str(award.get("awardable_id", ""))
    value = 1 if award.get("action", "") == "create" else -1

    return FeedbackEvent(
        project_id=project_id,
        discussion_id=note_id,
        event_type="award",
        value=value,
    )


def _gitlab_handle_note(payload: dict[str, Any]) -> FeedbackEvent | None:
    note = payload.get("object_attributes", {})
    project = payload.get("project", {})
    project_id = str(project.get("id", ""))
    discussion_id = note.get("discussion_id", "")
    body: str = note.get("note", "")

    event_type = _sentiment(body)
    if not event_type or not discussion_id:
        return None

    return FeedbackEvent(
        project_id=project_id,
        discussion_id=discussion_id,
        event_type=event_type,
        value=1,
    )


def _gitlab_handle_merge_request(payload: dict[str, Any]) -> list[FeedbackEvent]:
    attrs = payload.get("object_attributes", {})
    project = payload.get("project", {})
    project_id = str(project.get("id", ""))

    if attrs.get("action") != "update":
        return []

    events: list[FeedbackEvent] = []
    for discussion in payload.get("resolved_discussions", []):
        events.append(
            FeedbackEvent(
                project_id=project_id,
                discussion_id=discussion.get("id", ""),
                event_type="resolve",
                value=1,
            )
        )
    return events


# ---------------------------------------------------------------------------
# GitHub event handlers
# ---------------------------------------------------------------------------


def _github_repo_id(payload: dict[str, Any]) -> str:
    """Extract the ``owner/repo`` identifier from a GitHub webhook payload."""
    repo = payload.get("repository", {})
    return repo.get("full_name", str(repo.get("id", "")))


def _github_handle_pr_review(payload: dict[str, Any]) -> FeedbackEvent | None:
    """``pull_request_review`` — submitted review with 'approved' state."""
    action = payload.get("action", "")
    review = payload.get("review", {})
    if action != "submitted" or review.get("state", "").upper() != "APPROVED":
        return None

    project_id = _github_repo_id(payload)
    # Use the review ID as the discussion proxy key
    review_id = str(review.get("id", ""))
    if not review_id:
        return None

    return FeedbackEvent(
        project_id=project_id,
        discussion_id=review_id,
        event_type="resolve",
        value=1,
    )


def _github_handle_review_comment(payload: dict[str, Any]) -> FeedbackEvent | None:
    """``pull_request_review_comment`` — inline review comment (reply detection)."""
    action = payload.get("action", "")
    if action != "created":
        return None

    comment = payload.get("comment", {})
    project_id = _github_repo_id(payload)
    # Use in_reply_to_id when available so we trace back to the root comment
    discussion_id = str(comment.get("in_reply_to_id") or comment.get("id", ""))
    body: str = comment.get("body", "")

    event_type = _sentiment(body)
    if not event_type or not discussion_id:
        return None

    return FeedbackEvent(
        project_id=project_id,
        discussion_id=discussion_id,
        event_type=event_type,
        value=1,
    )


def _github_handle_issue_comment(payload: dict[str, Any]) -> FeedbackEvent | None:
    """``issue_comment`` — general PR comment (reply detection)."""
    action = payload.get("action", "")
    if action != "created":
        return None

    # Only care about PR comments, not plain issue comments
    if "pull_request" not in payload.get("issue", {}):
        return None

    comment = payload.get("comment", {})
    project_id = _github_repo_id(payload)
    discussion_id = str(comment.get("id", ""))
    body: str = comment.get("body", "")

    event_type = _sentiment(body)
    if not event_type or not discussion_id:
        return None

    return FeedbackEvent(
        project_id=project_id,
        discussion_id=discussion_id,
        event_type=event_type,
        value=1,
    )


def _github_handle_reaction(payload: dict[str, Any]) -> FeedbackEvent | None:
    """``reaction`` — thumbs-up/thumbs-down on a PR comment."""
    action = payload.get("action", "")  # "created" or "deleted"
    reaction = payload.get("reaction", {})
    content = reaction.get("content", "")

    # Only treat 👍 (+1) and 👎 (-1) as meaningful signals
    if content not in ("+1", "-1"):
        return None

    project_id = _github_repo_id(payload)
    comment = payload.get("comment", {})
    discussion_id = str(comment.get("id", ""))
    if not discussion_id:
        return None

    if action == "created":
        value = 1 if content == "+1" else -1
    else:  # deleted
        value = -1 if content == "+1" else 1

    return FeedbackEvent(
        project_id=project_id,
        discussion_id=discussion_id,
        event_type="award",
        value=value,
    )


# ---------------------------------------------------------------------------
# FastAPI endpoint
# ---------------------------------------------------------------------------


@app.post("/webhook")
async def webhook(
    request: Request,
    # GitLab headers
    x_gitlab_token: str | None = Header(default=None, alias="X-Gitlab-Token"),
    x_gitlab_event: str | None = Header(default=None, alias="X-Gitlab-Event"),
    # GitHub headers
    x_hub_signature_256: str | None = Header(
        default=None, alias="X-Hub-Signature-256"
    ),
    x_github_event: str | None = Header(default=None, alias="X-GitHub-Event"),
) -> dict[str, str]:
    body = await request.body()

    events: list[FeedbackEvent] = []

    if x_github_event:
        # GitHub webhook
        _verify_github_signature(body, x_hub_signature_256)
        payload: dict[str, Any] = await request.json()

        if x_github_event == "pull_request_review":
            event = _github_handle_pr_review(payload)
            if event:
                events.append(event)
        elif x_github_event == "pull_request_review_comment":
            event = _github_handle_review_comment(payload)
            if event:
                events.append(event)
        elif x_github_event == "issue_comment":
            event = _github_handle_issue_comment(payload)
            if event:
                events.append(event)
        elif x_github_event == "reaction":
            event = _github_handle_reaction(payload)
            if event:
                events.append(event)

        if events:
            logger.info("Processed %d GitHub feedback event(s).", len(events))

    elif x_gitlab_event:
        # GitLab webhook
        _verify_gitlab_token(x_gitlab_token)
        payload = await request.json()

        if x_gitlab_event == "Emoji Hook":
            event = _gitlab_handle_award(payload)
            if event:
                events.append(event)
        elif x_gitlab_event in ("Note Hook", "Confidential Note Hook"):
            event = _gitlab_handle_note(payload)
            if event:
                events.append(event)
        elif x_gitlab_event == "Merge Request Hook":
            events.extend(_gitlab_handle_merge_request(payload))

        if events:
            logger.info("Processed %d GitLab feedback event(s).", len(events))

    if events:
        with LessonStore() as store:
            for ev in events:
                store.apply_feedback(ev)

    return {"status": "ok", "processed": str(len(events))}


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy"}
