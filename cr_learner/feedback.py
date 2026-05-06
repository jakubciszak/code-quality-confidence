"""GitLab webhook receiver for feedback loop.

Listens for GitLab system hooks / project hooks and updates lesson scores:

* ``emoji`` event  → award (+1) or unaward (-1) on a note → :func:`_handle_award`
* ``note`` event   → reply to a bot comment analysed for sentiment →
                     ``reply_positive`` / ``reply_negative``
* ``merge_request`` event with ``action=update`` → check if a discussion was
  resolved → ``resolve``

Run with::

    cr-learner serve

or directly::

    uvicorn cr_learner.feedback:app --host 0.0.0.0 --port 8080
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request, status

from cr_learner.config import settings
from cr_learner.models import FeedbackEvent
from cr_learner.store import LessonStore

logger = logging.getLogger(__name__)

app = FastAPI(title="cr-learner feedback webhook", version="0.1.0")

# ---------------------------------------------------------------------------
# Webhook signature verification
# ---------------------------------------------------------------------------


def _verify_signature(body: bytes, token: str | None) -> None:
    """Verify the GitLab webhook secret token."""
    expected = settings.webhook_secret
    if not expected:
        return  # no secret configured — skip verification
    if token != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


# ---------------------------------------------------------------------------
# Event handlers
# ---------------------------------------------------------------------------


def _handle_award(payload: dict[str, Any]) -> FeedbackEvent | None:
    """Parse emoji (award/unaward) event."""
    award = payload.get("object_attributes", {})
    project = payload.get("project", {})
    project_id = str(project.get("id", ""))

    # Only care about emoji on notes (comments), not on the MR itself
    if award.get("awardable_type") != "Note":
        return None

    # Find the discussion_id — GitLab doesn't provide it directly in the award
    # event, so we piggyback on the note_id (used as a proxy key when no direct
    # mapping is stored yet; a production system would look up the discussion).
    note_id = str(award.get("awardable_id", ""))
    action = award.get("action", "")
    value = 1 if action == "create" else -1

    return FeedbackEvent(
        project_id=project_id,
        discussion_id=note_id,
        event_type="award",
        value=value,
    )


def _handle_note(payload: dict[str, Any]) -> FeedbackEvent | None:
    """Parse note (comment) event — detect positive/negative replies to bot."""
    note = payload.get("object_attributes", {})
    project = payload.get("project", {})
    project_id = str(project.get("id", ""))
    discussion_id = note.get("discussion_id", "")
    body: str = note.get("note", "").lower()

    # Simple heuristic: replies with positive keywords → positive feedback
    positive_kw = {"lgtm", "fixed", "done", "thanks", "good catch", "applied", "resolved"}
    negative_kw = {"disagree", "no", "won't fix", "wontfix", "not applicable", "false positive"}

    event_type: str | None = None
    if any(kw in body for kw in positive_kw):
        event_type = "reply_positive"
    elif any(kw in body for kw in negative_kw):
        event_type = "reply_negative"

    if not event_type or not discussion_id:
        return None

    return FeedbackEvent(
        project_id=project_id,
        discussion_id=discussion_id,
        event_type=event_type,
        value=1,
    )


def _handle_merge_request(payload: dict[str, Any]) -> list[FeedbackEvent]:
    """Parse merge_request event — detect resolved discussions."""
    attrs = payload.get("object_attributes", {})
    project = payload.get("project", {})
    project_id = str(project.get("id", ""))

    if attrs.get("action") != "update":
        return []

    # GitLab MR update events don't directly carry resolved-discussion info;
    # in a production system you'd diff the discussion list via REST.
    # Here we emit a resolve event for each discussion in the payload if present.
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
# FastAPI endpoint
# ---------------------------------------------------------------------------


@app.post("/webhook")
async def webhook(
    request: Request,
    x_gitlab_token: str | None = Header(default=None, alias="X-Gitlab-Token"),
    x_gitlab_event: str | None = Header(default=None, alias="X-Gitlab-Event"),
) -> dict[str, str]:
    body = await request.body()
    _verify_signature(body, x_gitlab_token)

    payload: dict[str, Any] = await request.json()

    events: list[FeedbackEvent] = []

    if x_gitlab_event == "Emoji Hook":
        event = _handle_award(payload)
        if event:
            events.append(event)
    elif x_gitlab_event in ("Note Hook", "Confidential Note Hook"):
        event = _handle_note(payload)
        if event:
            events.append(event)
    elif x_gitlab_event in ("Merge Request Hook",):
        events.extend(_handle_merge_request(payload))

    if events:
        with LessonStore() as store:
            for ev in events:
                store.apply_feedback(ev)
        logger.info("Processed %d feedback event(s) from GitLab.", len(events))

    return {"status": "ok", "processed": str(len(events))}


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy"}
