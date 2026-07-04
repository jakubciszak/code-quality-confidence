import json

from conftest import git, load_script, run_script

snap = load_script("diff_snapshot")


def test_classify_paths():
    assert "security" in snap.classify("src/auth/login.py")
    assert "tests" in snap.classify("tests/test_login.py")
    assert "docs" in snap.classify("docs/guide.md")
    assert "deps" in snap.classify("requirements.txt")
    assert "db" in snap.classify("migrations/0002_add_users.sql")
    assert "ci" in snap.classify(".github/workflows/ci.yml")
    assert snap.classify("src/service.py") == {"code"}


def _agents(picked):
    return set(picked)


def test_select_agents_security_change():
    files = [{"path": "src/auth/login.py", "added": 10, "deleted": 0,
              "status": "M", "categories": {"code", "security"}}]
    picked, skipped = snap.select_agents(files, {"risky_lines": {"password"}, "api_surface": False}, False)
    assert {"correctness", "security", "tests"} <= _agents(picked)
    assert "performance" in skipped


def test_select_agents_docs_only_change():
    files = [{"path": "README.md", "added": 3, "deleted": 1,
              "status": "M", "categories": {"docs"}}]
    picked, skipped = snap.select_agents(files, {"risky_lines": set(), "api_surface": False}, False)
    assert _agents(picked) == {"docs"}
    assert set(skipped) == {"correctness", "security", "architecture", "performance", "tests"}


def test_select_agents_forced_all():
    picked, skipped = snap.select_agents([], {"risky_lines": set(), "api_surface": False}, True)
    assert _agents(picked) == {"correctness", "security", "architecture",
                               "performance", "tests", "docs"}
    assert skipped == {}


def test_snapshot_end_to_end(git_repo):
    (git_repo / "src" / "auth.py").write_text(
        "def login(user, password):\n    return 'SELECT * FROM users'\n")
    git(git_repo, "add", "-A")

    result = run_script("diff_snapshot", "--staged", cwd=git_repo)
    assert result.returncode == 0
    manifest = json.loads(result.stdout)

    assert manifest["totals"]["files"] == 1
    assert (git_repo / ".swiss-cheese" / "runs" / "latest" / "diff.patch").exists()
    saved = json.loads((git_repo / ".swiss-cheese" / "runs" / "latest" / "manifest.json").read_text())
    assert saved["totals"] == manifest["totals"]

    recommended = {r["agent"] for r in manifest["recommended_reviews"]}
    assert "security" in recommended  # auth path + password/SELECT in added lines
    assert "tests" in recommended    # code without test changes
    # every skip carries a reason
    assert all(s["reason"] for s in manifest["skipped_reviews"])


def test_snapshot_empty_diff(git_repo):
    result = run_script("diff_snapshot", cwd=git_repo)
    assert result.returncode == 0
    assert json.loads(result.stdout)["empty"] is True
