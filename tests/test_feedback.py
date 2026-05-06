"""Tests for cr_learner.feedback (FastAPI webhook)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from cr_learner.feedback import _handle_award, _handle_merge_request, _handle_note, app

# ---------------------------------------------------------------------------
# Helper payloads
# ---------------------------------------------------------------------------


def _award_payload(action: str = "create", awardable_type: str = "Note") -> dict:
    return {
        "object_attributes": {
            "awardable_type": awardable_type,
            "awardable_id": 999,
            "action": action,
        },
        "project": {"id": 42},
    }


def _note_payload(body: str, discussion_id: str = "disc-1") -> dict:
    return {
        "object_attributes": {
            "note": body,
            "discussion_id": discussion_id,
        },
        "user": {"username": "bob"},
        "project": {"id": 42},
    }


def _mr_update_payload(resolved_discussions: list[dict] | None = None) -> dict:
    return {
        "object_attributes": {"action": "update"},
        "project": {"id": 42},
        "resolved_discussions": resolved_discussions or [],
    }


# ---------------------------------------------------------------------------
# Unit tests for event handlers
# ---------------------------------------------------------------------------


class TestHandleAward:
    def test_returns_award_event_for_note(self):
        event = _handle_award(_award_payload("create", "Note"))
        assert event is not None
        assert event.event_type == "award"
        assert event.value == 1
        assert event.project_id == "42"

    def test_returns_negative_for_unaward(self):
        event = _handle_award(_award_payload("destroy", "Note"))
        assert event is not None
        assert event.value == -1

    def test_returns_none_for_non_note_awardable(self):
        event = _handle_award(_award_payload("create", "MergeRequest"))
        assert event is None


class TestHandleNote:
    def test_positive_keyword_triggers_reply_positive(self):
        for kw in ["lgtm", "fixed", "done", "thanks", "applied"]:
            event = _handle_note(_note_payload(kw))
            assert event is not None
            assert event.event_type == "reply_positive"

    def test_negative_keyword_triggers_reply_negative(self):
        for kw in ["disagree", "won't fix", "wontfix", "false positive"]:
            event = _handle_note(_note_payload(kw))
            assert event is not None
            assert event.event_type == "reply_negative"

    def test_neutral_note_returns_none(self):
        event = _handle_note(_note_payload("I have a question about this code."))
        assert event is None

    def test_missing_discussion_id_returns_none(self):
        payload = _note_payload("lgtm", discussion_id="")
        event = _handle_note(payload)
        assert event is None


class TestHandleMergeRequest:
    def test_returns_resolve_events_for_resolved_discussions(self):
        payload = _mr_update_payload([{"id": "disc-99"}, {"id": "disc-100"}])
        events = _handle_merge_request(payload)
        assert len(events) == 2
        assert all(e.event_type == "resolve" for e in events)

    def test_non_update_action_returns_empty(self):
        payload = {
            "object_attributes": {"action": "merge"},
            "project": {"id": 42},
            "resolved_discussions": [{"id": "disc-1"}],
        }
        events = _handle_merge_request(payload)
        assert events == []

    def test_no_resolved_discussions_returns_empty(self):
        events = _handle_merge_request(_mr_update_payload([]))
        assert events == []


# ---------------------------------------------------------------------------
# FastAPI endpoint tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def client():
    return TestClient(app, raise_server_exceptions=True)


class TestWebhookEndpoint:
    @patch("cr_learner.feedback.LessonStore")
    def test_emoji_hook_processes_award(self, mock_store_cls, client):
        mock_store = MagicMock()
        mock_store_cls.return_value.__enter__ = MagicMock(return_value=mock_store)
        mock_store_cls.return_value.__exit__ = MagicMock(return_value=False)

        resp = client.post(
            "/webhook",
            json=_award_payload("create", "Note"),
            headers={"X-Gitlab-Event": "Emoji Hook"},
        )
        assert resp.status_code == 200
        assert resp.json()["processed"] == "1"

    @patch("cr_learner.feedback.LessonStore")
    def test_note_hook_positive_processes(self, mock_store_cls, client):
        mock_store = MagicMock()
        mock_store_cls.return_value.__enter__ = MagicMock(return_value=mock_store)
        mock_store_cls.return_value.__exit__ = MagicMock(return_value=False)

        resp = client.post(
            "/webhook",
            json=_note_payload("lgtm"),
            headers={"X-Gitlab-Event": "Note Hook"},
        )
        assert resp.status_code == 200
        assert resp.json()["processed"] == "1"

    @patch("cr_learner.feedback.LessonStore")
    def test_unrecognised_event_returns_ok_with_zero(self, mock_store_cls, client):
        resp = client.post(
            "/webhook",
            json={"some": "data"},
            headers={"X-Gitlab-Event": "Push Hook"},
        )
        assert resp.status_code == 200
        assert resp.json()["processed"] == "0"

    def test_health_endpoint(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "healthy"}

    def test_invalid_token_returns_401(self, client):
        # Set a webhook secret and send wrong token
        import cr_learner.config as cfg

        original_secret = cfg.settings.webhook_secret
        cfg.settings.webhook_secret = "correct-secret"
        try:
            resp = client.post(
                "/webhook",
                json=_award_payload(),
                headers={
                    "X-Gitlab-Event": "Emoji Hook",
                    "X-Gitlab-Token": "wrong-secret",
                },
            )
            assert resp.status_code == 401
        finally:
            cfg.settings.webhook_secret = original_secret
