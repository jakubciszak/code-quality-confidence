"""Tests for cr_learner.extractors."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from cr_learner.extractors import (
    GitHubExtractor,
    GitLabExtractor,
    LessonExtractor,
    MRExtractor,
    code_changed_after_comment,
    get_extractor,
)
from cr_learner.models import (
    DiffVersion,
    Discussion,
    DiscussionNote,
    MRData,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_version(iid: int, days_offset: int = 0) -> DiffVersion:
    """Helper to build a DiffVersion with a given offset in days from epoch."""
    ts = datetime(2024, 1, 1 + days_offset, tzinfo=UTC)
    return DiffVersion(
        id=iid,
        head_sha=f"abc{iid:03d}",
        base_commit_sha="base000",
        start_commit_sha="start000",
        created_at=ts,
        state="collected",
    )


def _make_note(
    nid: int,
    author: str,
    body: str,
    days_offset: int = 0,
    resolved: bool = False,
) -> DiscussionNote:
    ts = datetime(2024, 1, 1 + days_offset, tzinfo=UTC)
    return DiscussionNote(
        id=nid,
        author_username=author,
        author_name=author.title(),
        body=body,
        created_at=ts,
        updated_at=ts,
        resolved=resolved,
    )


def _make_discussion(
    did: str,
    notes: list[DiscussionNote],
    resolved: bool = False,
) -> Discussion:
    return Discussion(id=did, notes=notes, resolved=resolved, resolvable=True)


@pytest.fixture()
def sample_mr() -> MRData:
    return MRData(
        mr_id=1,
        mr_iid=42,
        project_id="99",
        title="Feat: add keyset pagination",
        description="Replaces OFFSET with keyset pagination",
        state="merged",
        target_branch="main",
        source_branch="feat/keyset-pagination",
        author_username="alice",
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
        merged_at=datetime(2024, 1, 5, tzinfo=UTC),
        labels=["backend"],
        diff="--- a/repo.py\n+++ b/repo.py\n@@ -1 +1 @@\n-OFFSET\n+keyset",
        discussions=[
            _make_discussion(
                "disc-1",
                [
                    _make_note(
                        10, "bob", "Use keyset pagination instead of OFFSET.", days_offset=1
                    ),
                    _make_note(11, "alice", "Done, fixed!", days_offset=3),
                ],
                resolved=True,
            )
        ],
        versions=[_make_version(1, 0), _make_version(2, 2), _make_version(3, 4)],
        approvals=["bob"],
    )


# ---------------------------------------------------------------------------
# code_changed_after_comment
# ---------------------------------------------------------------------------


class TestCodeChangedAfterComment:
    def test_returns_true_when_version_after_comment(self):
        comment_time = datetime(2024, 1, 2, tzinfo=UTC)
        versions = [_make_version(1, 0), _make_version(2, 3)]  # day 3 > day 2
        assert code_changed_after_comment(comment_time, versions) is True

    def test_returns_false_when_no_version_after_comment(self):
        comment_time = datetime(2024, 1, 5, tzinfo=UTC)
        versions = [_make_version(1, 0), _make_version(2, 2)]  # all before day 5
        assert code_changed_after_comment(comment_time, versions) is False

    def test_returns_false_for_empty_versions(self):
        comment_time = datetime(2024, 1, 1, tzinfo=UTC)
        assert code_changed_after_comment(comment_time, []) is False

    def test_handles_naive_datetimes(self):
        comment_time = datetime(2024, 1, 2)  # naive
        versions = [
            DiffVersion(
                id=1,
                head_sha="abc",
                base_commit_sha="base",
                start_commit_sha="start",
                created_at=datetime(2024, 1, 3),  # also naive, but later
                state="collected",
            )
        ]
        assert code_changed_after_comment(comment_time, versions) is True


# ---------------------------------------------------------------------------
# LessonExtractor
# ---------------------------------------------------------------------------


class TestLessonExtractor:
    def _mock_claude_response(self, json_text: str):
        """Return a mock Anthropic response object."""
        msg = MagicMock()
        content_block = MagicMock()
        content_block.text = json_text
        msg.content = [content_block]
        return msg

    @patch("cr_learner.extractors.anthropic.Anthropic")
    def test_extracts_lesson_from_resolved_discussion(self, mock_anthropic, sample_mr):
        mock_client = MagicMock()
        mock_anthropic.return_value = mock_client
        mock_client.messages.create.return_value = self._mock_claude_response(
            '{"domain":"python","problematic_code":"OFFSET","reviewer_comment":'
            '"Use keyset pagination instead of OFFSET for event stores.",'
            '"author_fix":"Replaced OFFSET with keyset cursor.",'
            '"rule_text":"Prefer keyset pagination over OFFSET in event stores."}'
        )

        extractor = LessonExtractor()
        lesson = extractor.extract(sample_mr, sample_mr.discussions[0])

        assert lesson is not None
        assert lesson.domain == "python"
        assert "keyset" in lesson.rule_text.lower()
        assert lesson.signals.resolved is True
        assert lesson.signals.code_changed_after is True  # version 2 after comment day 1
        assert lesson.signals.authority_score == 0.7  # bob is in approvals

    @patch("cr_learner.extractors.anthropic.Anthropic")
    def test_returns_none_when_llm_returns_empty_rule(self, mock_anthropic, sample_mr):
        mock_client = MagicMock()
        mock_anthropic.return_value = mock_client
        mock_client.messages.create.return_value = self._mock_claude_response(
            '{"rule_text": ""}'
        )

        extractor = LessonExtractor()
        lesson = extractor.extract(sample_mr, sample_mr.discussions[0])
        assert lesson is None

    @patch("cr_learner.extractors.anthropic.Anthropic")
    def test_returns_none_for_non_json_llm_response(self, mock_anthropic, sample_mr):
        mock_client = MagicMock()
        mock_anthropic.return_value = mock_client
        mock_client.messages.create.return_value = self._mock_claude_response(
            "Sorry, I cannot extract a lesson."
        )

        extractor = LessonExtractor()
        lesson = extractor.extract(sample_mr, sample_mr.discussions[0])
        assert lesson is None

    @patch("cr_learner.extractors.anthropic.Anthropic")
    def test_authority_score_lower_for_non_approver(self, mock_anthropic, sample_mr):
        mock_client = MagicMock()
        mock_anthropic.return_value = mock_client
        mock_client.messages.create.return_value = self._mock_claude_response(
            '{"domain":"general","problematic_code":"","reviewer_comment":"Fix this.",'
            '"author_fix":"","rule_text":"Always fix this."}'
        )

        # Discussion started by 'charlie' who is NOT in approvals
        discussion = _make_discussion(
            "disc-2",
            [_make_note(20, "charlie", "Fix this.", days_offset=1)],
            resolved=True,
        )

        extractor = LessonExtractor()
        lesson = extractor.extract(sample_mr, discussion)

        assert lesson is not None
        assert lesson.signals.authority_score == 0.5  # not an approver


# ---------------------------------------------------------------------------
# MRExtractor (integration — requires real GitLab; tested with mocks)
# ---------------------------------------------------------------------------


class TestMRExtractor:
    @patch("cr_learner.extractors._get_gitlab_client")
    def test_extract_calls_gitlab_api(self, mock_get_client):
        mock_gl = MagicMock()
        mock_get_client.return_value = mock_gl

        project = MagicMock()
        mock_gl.projects.get.return_value = project

        mr = MagicMock()
        mr.id = 1
        mr.iid = 42
        mr.title = "Test MR"
        mr.description = "desc"
        mr.state = "merged"
        mr.target_branch = "main"
        mr.source_branch = "feat"
        mr.author = {"username": "alice"}
        mr.created_at = "2024-01-01T00:00:00Z"
        mr.merged_at = "2024-01-05T00:00:00Z"
        mr.labels = []
        mr.diffs.list.return_value = []
        mr.discussions.list.return_value = []
        mr.approvals.get.return_value = MagicMock(approved_by=[])
        mr.pipelines.list.return_value = []
        mr.closes_issues.return_value = []

        project.mergerequests.get.return_value = mr

        extractor = MRExtractor("99")
        mr_data = extractor.extract(42)

        assert mr_data.mr_iid == 42
        assert mr_data.project_id == "99"
        assert mr_data.author_username == "alice"
        assert mr_data.platform == "gitlab"


# ---------------------------------------------------------------------------
# GitHubExtractor (unit — mocked PyGithub client)
# ---------------------------------------------------------------------------


def _make_gh_commit(sha: str, author_date: datetime, parent_sha: str = ""):
    commit = MagicMock()
    commit.sha = sha
    commit.commit.author.date = author_date
    if parent_sha:
        parent = MagicMock()
        parent.sha = parent_sha
        commit.parents = [parent]
    else:
        commit.parents = []
    return commit


def _make_gh_review_comment(
    cid: int,
    login: str,
    body: str,
    created: datetime,
    in_reply_to_id: int | None = None,
    path: str = "file.py",
):
    c = MagicMock()
    c.id = cid
    c.user.login = login
    c.user.name = login.title()
    c.body = body
    c.created_at = created
    c.updated_at = created
    c.in_reply_to_id = in_reply_to_id
    c.path = path
    c.line = 10
    return c


def _make_gh_issue_comment(cid: int, login: str, body: str, created: datetime):
    c = MagicMock()
    c.id = cid
    c.user.login = login
    c.user.name = login.title()
    c.body = body
    c.created_at = created
    c.updated_at = created
    return c


def _make_gh_review(login: str, state: str):
    r = MagicMock()
    r.user.login = login
    r.state = state
    return r


def _mock_github_pr(number: int = 42):
    """Return a mock GitHub PR object."""
    pr = MagicMock()
    pr.number = number
    pr.title = "Add keyset pagination"
    pr.body = "Replaces OFFSET"
    pr.state = "closed"
    pr.base.ref = "main"
    pr.head.ref = "feat/keyset"
    pr.head.sha = "head-sha"
    pr.user.login = "alice"
    ts = datetime(2024, 1, 1, tzinfo=UTC)
    pr.created_at = ts
    pr.merged_at = datetime(2024, 1, 5, tzinfo=UTC)
    pr.labels = []

    pr.get_files.return_value = [
        MagicMock(filename="repo.py", patch="@@ -1 +1 @@\n-OFFSET\n+keyset"),
    ]

    pr.get_review_comments.return_value = [
        _make_gh_review_comment(
            101, "bob", "Use keyset pagination instead of OFFSET.",
            datetime(2024, 1, 2, tzinfo=UTC),
        ),
        _make_gh_review_comment(
            102, "alice", "Done, fixed!",
            datetime(2024, 1, 4, tzinfo=UTC),
            in_reply_to_id=101,
        ),
    ]
    pr.get_issue_comments.return_value = []
    pr.get_commits.return_value = [
        _make_gh_commit("sha-v1", datetime(2024, 1, 1, tzinfo=UTC)),
        _make_gh_commit("sha-v2", datetime(2024, 1, 3, tzinfo=UTC), "sha-v1"),
    ]
    pr.get_reviews.return_value = [_make_gh_review("bob", "APPROVED")]
    return pr


class TestGitHubExtractor:
    @patch("cr_learner.extractors.Github")
    @patch("cr_learner.extractors.Auth")
    def test_extract_returns_mrdata(self, mock_auth, mock_github_cls):
        mock_gh = MagicMock()
        mock_github_cls.return_value = mock_gh
        mock_repo = MagicMock()
        mock_gh.get_repo.return_value = mock_repo
        mock_repo.get_pull.return_value = _mock_github_pr(42)
        mock_repo.get_commit.return_value = MagicMock(
            get_combined_status=MagicMock(return_value=MagicMock(state="success"))
        )

        extractor = GitHubExtractor(repo="myorg/myrepo")
        data = extractor.extract(42)

        assert data.mr_iid == 42
        assert data.project_id == "myorg/myrepo"
        assert data.author_username == "alice"
        assert data.platform == "github"

    @patch("cr_learner.extractors.Github")
    @patch("cr_learner.extractors.Auth")
    def test_extract_maps_approvals_from_reviews(self, mock_auth, mock_github_cls):
        mock_gh = MagicMock()
        mock_github_cls.return_value = mock_gh
        mock_repo = MagicMock()
        mock_gh.get_repo.return_value = mock_repo
        pr = _mock_github_pr()
        pr.get_reviews.return_value = [
            _make_gh_review("bob", "APPROVED"),
            _make_gh_review("charlie", "CHANGES_REQUESTED"),
        ]
        mock_repo.get_pull.return_value = pr
        mock_repo.get_commit.return_value = MagicMock(
            get_combined_status=MagicMock(return_value=MagicMock(state="success"))
        )

        extractor = GitHubExtractor(repo="myorg/myrepo")
        data = extractor.extract(42)

        assert "bob" in data.approvals
        assert "charlie" not in data.approvals

    @patch("cr_learner.extractors.Github")
    @patch("cr_learner.extractors.Auth")
    def test_extract_maps_commits_to_versions(self, mock_auth, mock_github_cls):
        mock_gh = MagicMock()
        mock_github_cls.return_value = mock_gh
        mock_repo = MagicMock()
        mock_gh.get_repo.return_value = mock_repo
        mock_repo.get_pull.return_value = _mock_github_pr()
        mock_repo.get_commit.return_value = MagicMock(
            get_combined_status=MagicMock(return_value=MagicMock(state="success"))
        )

        extractor = GitHubExtractor(repo="myorg/myrepo")
        data = extractor.extract(42)

        assert len(data.versions) == 2
        assert data.versions[0].head_sha == "sha-v1"
        assert data.versions[1].head_sha == "sha-v2"

    @patch("cr_learner.extractors.Github")
    @patch("cr_learner.extractors.Auth")
    def test_review_comments_grouped_by_thread(self, mock_auth, mock_github_cls):
        """Reply comments should be grouped with the root under the same Discussion."""
        mock_gh = MagicMock()
        mock_github_cls.return_value = mock_gh
        mock_repo = MagicMock()
        mock_gh.get_repo.return_value = mock_repo
        mock_repo.get_pull.return_value = _mock_github_pr()
        mock_repo.get_commit.return_value = MagicMock(
            get_combined_status=MagicMock(return_value=MagicMock(state="success"))
        )

        extractor = GitHubExtractor(repo="myorg/myrepo")
        data = extractor.extract(42)

        # The two review comments (root=101 and reply 102→101) form one thread
        inline_threads = [d for d in data.discussions if d.resolvable]
        assert len(inline_threads) == 1
        assert len(inline_threads[0].notes) == 2

    @patch("cr_learner.extractors.Github")
    @patch("cr_learner.extractors.Auth")
    def test_list_merged_pr_numbers(self, mock_auth, mock_github_cls):
        mock_gh = MagicMock()
        mock_github_cls.return_value = mock_gh
        mock_repo = MagicMock()
        mock_gh.get_repo.return_value = mock_repo

        merged_pr = MagicMock()
        merged_pr.number = 7
        merged_pr.merged_at = datetime(2024, 1, 5, tzinfo=UTC)

        open_pr = MagicMock()
        open_pr.number = 8
        open_pr.merged_at = None

        mock_repo.get_pulls.return_value = [merged_pr, open_pr]

        extractor = GitHubExtractor(repo="myorg/myrepo")
        numbers = extractor.list_merged_pr_numbers(limit=10)

        assert numbers == [7]


# ---------------------------------------------------------------------------
# get_extractor factory
# ---------------------------------------------------------------------------


class TestGetExtractor:
    @patch("cr_learner.extractors._get_gitlab_client")
    def test_returns_gitlab_extractor(self, mock_get_client):
        mock_gl = MagicMock()
        mock_get_client.return_value = mock_gl
        mock_gl.projects.get.return_value = MagicMock()

        extractor = get_extractor(platform="gitlab", project_id="99")
        assert isinstance(extractor, GitLabExtractor)

    @patch("cr_learner.extractors.Github")
    @patch("cr_learner.extractors.Auth")
    def test_returns_github_extractor(self, mock_auth, mock_github_cls):
        mock_gh = MagicMock()
        mock_github_cls.return_value = mock_gh
        mock_gh.get_repo.return_value = MagicMock()

        extractor = get_extractor(platform="github", project_id="org/repo")
        assert isinstance(extractor, GitHubExtractor)

    def test_raises_for_unknown_platform(self):
        with pytest.raises(ValueError, match="Unknown platform"):
            get_extractor(platform="bitbucket")

    @patch("cr_learner.extractors._get_gitlab_client")
    def test_mr_extractor_is_gitlab_alias(self, mock_get_client):
        mock_gl = MagicMock()
        mock_get_client.return_value = mock_gl
        mock_gl.projects.get.return_value = MagicMock()

        extractor = MRExtractor("99")
        assert isinstance(extractor, GitLabExtractor)
