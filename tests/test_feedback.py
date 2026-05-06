"""Tests for cr_learner.feedback (FastAPI webhook)."""
from __future__ import annotations

import hashlib
import hmac
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from cr_learner.feedback import (
    _github_handle_issue_comment,
    _github_handle_pr_review,
    _github_handle_reaction,
    _github_handle_review_comment,
    _gitlab_handle_award,
    _gitlab_handle_merge_request,
    _gitlab_handle_note,
    app,
)

# ---------------------------------------------------------------------------
# GitLab helper payloads
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
# GitHub helper payloads
# ---------------------------------------------------------------------------


def _gh_repo() -> dict:
    return {"full_name": "myorg/myrepo", "id": 123}


def _gh_pr_review_payload(action: str = "submitted", state: str = "approved") -> dict:
    return {
        "action": action,
        "review": {"id": 777, "state": state},
        "repository": _gh_repo(),
    }


def _gh_review_comment_payload(
    action: str = "created",
    body: str = "lgtm",
    comment_id: int = 500,
    in_reply_to_id: int | None = 400,
) -> dict:
    return {
        "action": action,
        "comment": {
            "id": comment_id,
            "body": body,
            "in_reply_to_id": in_reply_to_id,
        },
        "repository": _gh_repo(),
    }


def _gh_issue_comment_payload(
    action: str = "created",
    body: str = "lgtm",
    comment_id: int = 600,
) -> dict:
    return {
        "action": action,
        "comment": {"id": comment_id, "body": body},
        "issue": {"number": 1, "pull_request": {"url": "https://api.github.com/..."}},
        "repository": _gh_repo(),
    }


def _gh_reaction_payload(
    action: str = "created",
    content: str = "+1",
    comment_id: int = 700,
) -> dict:
    return {
        "action": action,
        "reaction": {"content": content},
        "comment": {"id": comment_id},
        "repository": _gh_repo(),
    }


# ---------------------------------------------------------------------------
# GitLab unit tests
# ---------------------------------------------------------------------------


class TestGitLabHandleAward:
    def test_returns_award_event_for_note(self):
        event = _gitlab_handle_award(_award_payload("create", "Note"))
        assert event is not None
        assert event.event_type == "award"
        assert event.value == 1
        assert event.project_id == "42"

    def test_returns_negative_for_unaward(self):
        event = _gitlab_handle_award(_award_payload("destroy", "Note"))
        assert event is not None
        assert event.value == -1

    def test_returns_none_for_non_note_awardable(self):
        event = _gitlab_handle_award(_award_payload("create", "MergeRequest"))
        assert event is None


class TestGitLabHandleNote:
    def test_positive_keyword_triggers_reply_positive(self):
        for kw in ["lgtm", "fixed", "done", "thanks", "applied"]:
            event = _gitlab_handle_note(_note_payload(kw))
            assert event is not None
            assert event.event_type == "reply_positive"

    def test_negative_keyword_triggers_reply_negative(self):
        for kw in ["disagree", "won't fix", "wontfix", "false positive"]:
            event = _gitlab_handle_note(_note_payload(kw))
            assert event is not None
            assert event.event_type == "reply_negative"

    def test_neutral_note_returns_none(self):
        event = _gitlab_handle_note(_note_payload("I have a question about this code."))
        assert event is None

    def test_missing_discussion_id_returns_none(self):
        event = _gitlab_handle_note(_note_payload("lgtm", discussion_id=""))
        assert event is None


class TestGitLabHandleMergeRequest:
    def test_returns_resolve_events_for_resolved_discussions(self):
        payload = _mr_update_payload([{"id": "disc-99"}, {"id": "disc-100"}])
        events = _gitlab_handle_merge_request(payload)
        assert len(events) == 2
        assert all(e.event_type == "resolve" for e in events)

    def test_non_update_action_returns_empty(self):
        payload = {
            "object_attributes": {"action": "merge"},
            "project": {"id": 42},
            "resolved_discussions": [{"id": "disc-1"}],
        }
        assert _gitlab_handle_merge_request(payload) == []

    def test_no_resolved_discussions_returns_empty(self):
        assert _gitlab_handle_merge_request(_mr_update_payload([])) == []


# ---------------------------------------------------------------------------
# GitHub unit tests
# ---------------------------------------------------------------------------


class TestGitHubHandlePRReview:
    def test_approved_review_returns_resolve_event(self):
        event = _github_handle_pr_review(_gh_pr_review_payload("submitted", "approved"))
        assert event is not None
        assert event.event_type == "resolve"
        assert event.value == 1
        assert event.project_id == "myorg/myrepo"
        assert event.discussion_id == "777"

    def test_changes_requested_returns_none(self):
        event = _github_handle_pr_review(
            _gh_pr_review_payload("submitted", "changes_requested")
        )
        assert event is None

    def test_non_submitted_action_returns_none(self):
        event = _github_handle_pr_review(_gh_pr_review_payload("dismissed", "approved"))
        assert event is None


class TestGitHubHandleReviewComment:
    def test_positive_reply_returns_reply_positive(self):
        event = _github_handle_review_comment(
            _gh_review_comment_payload(body="lgtm", in_reply_to_id=400)
        )
        assert event is not None
        assert event.event_type == "reply_positive"
        assert event.discussion_id == "400"  # uses in_reply_to_id as root

    def test_negative_reply_returns_reply_negative(self):
        event = _github_handle_review_comment(
            _gh_review_comment_payload(body="disagree with this")
        )
        assert event is not None
        assert event.event_type == "reply_negative"

    def test_neutral_comment_returns_none(self):
        event = _github_handle_review_comment(
            _gh_review_comment_payload(body="interesting approach")
        )
        assert event is None

    def test_non_created_action_returns_none(self):
        event = _github_handle_review_comment(
            _gh_review_comment_payload(action="edited", body="lgtm")
        )
        assert event is None

    def test_uses_own_id_when_no_reply_to(self):
        event = _github_handle_review_comment(
            _gh_review_comment_payload(body="done", comment_id=500, in_reply_to_id=None)
        )
        assert event is not None
        assert event.discussion_id == "500"


class TestGitHubHandleIssueComment:
    def test_positive_pr_comment_returns_event(self):
        event = _github_handle_issue_comment(_gh_issue_comment_payload(body="done"))
        assert event is not None
        assert event.event_type == "reply_positive"

    def test_non_pr_issue_comment_returns_none(self):
        payload = {
            "action": "created",
            "comment": {"id": 1, "body": "lgtm"},
            "issue": {"number": 1},  # no pull_request key
            "repository": _gh_repo(),
        }
        event = _github_handle_issue_comment(payload)
        assert event is None

    def test_non_created_action_returns_none(self):
        event = _github_handle_issue_comment(
            _gh_issue_comment_payload(action="edited", body="lgtm")
        )
        assert event is None


class TestGitHubHandleReaction:
    def test_thumbsup_created_returns_award_plus1(self):
        event = _github_handle_reaction(_gh_reaction_payload("created", "+1"))
        assert event is not None
        assert event.event_type == "award"
        assert event.value == 1

    def test_thumbsdown_created_returns_award_minus1(self):
        event = _github_handle_reaction(_gh_reaction_payload("created", "-1"))
        assert event is not None
        assert event.value == -1

    def test_thumbsup_deleted_reverses_value(self):
        event = _github_handle_reaction(_gh_reaction_payload("deleted", "+1"))
        assert event is not None
        assert event.value == -1

    def test_non_thumbs_reaction_returns_none(self):
        event = _github_handle_reaction(_gh_reaction_payload("created", "heart"))
        assert event is None


# ---------------------------------------------------------------------------
# FastAPI endpoint tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def client():
    return TestClient(app, raise_server_exceptions=True)


class TestWebhookEndpoint:
    @patch("cr_learner.feedback.LessonStore")
    def test_gitlab_emoji_hook_processes_award(self, mock_store_cls, client):
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
    def test_gitlab_note_hook_positive_processes(self, mock_store_cls, client):
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
    def test_github_pr_review_approved_processes(self, mock_store_cls, client):
        mock_store = MagicMock()
        mock_store_cls.return_value.__enter__ = MagicMock(return_value=mock_store)
        mock_store_cls.return_value.__exit__ = MagicMock(return_value=False)

        resp = client.post(
            "/webhook",
            json=_gh_pr_review_payload("submitted", "approved"),
            headers={"X-GitHub-Event": "pull_request_review"},
        )
        assert resp.status_code == 200
        assert resp.json()["processed"] == "1"

    @patch("cr_learner.feedback.LessonStore")
    def test_github_reaction_thumbsup_processes(self, mock_store_cls, client):
        mock_store = MagicMock()
        mock_store_cls.return_value.__enter__ = MagicMock(return_value=mock_store)
        mock_store_cls.return_value.__exit__ = MagicMock(return_value=False)

        resp = client.post(
            "/webhook",
            json=_gh_reaction_payload("created", "+1"),
            headers={"X-GitHub-Event": "reaction"},
        )
        assert resp.status_code == 200
        assert resp.json()["processed"] == "1"

    @patch("cr_learner.feedback.LessonStore")
    def test_unrecognised_gitlab_event_returns_ok_with_zero(self, mock_store_cls, client):
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

    def test_invalid_gitlab_token_returns_401(self, client):
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

    def test_invalid_github_signature_returns_401(self, client):
        import cr_learner.config as cfg

        original_secret = cfg.settings.webhook_secret
        cfg.settings.webhook_secret = "correct-secret"
        try:
            resp = client.post(
                "/webhook",
                json=_gh_pr_review_payload(),
                headers={
                    "X-GitHub-Event": "pull_request_review",
                    "X-Hub-Signature-256": "sha256=bad-sig",
                },
            )
            assert resp.status_code == 401
        finally:
            cfg.settings.webhook_secret = original_secret

    def test_valid_github_signature_is_accepted(self, client):
        import json

        import cr_learner.config as cfg

        original_secret = cfg.settings.webhook_secret
        secret = "my-test-secret"
        cfg.settings.webhook_secret = secret
        try:
            body = json.dumps(_gh_pr_review_payload("submitted", "changes_requested")).encode()
            sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
            resp = client.post(
                "/webhook",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-GitHub-Event": "pull_request_review",
                    "X-Hub-Signature-256": sig,
                },
            )
            # changes_requested → 0 events, but should not 401
            assert resp.status_code == 200
        finally:
            cfg.settings.webhook_secret = original_secret
