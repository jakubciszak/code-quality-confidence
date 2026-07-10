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


def test_ecosystem_detection():
    assert snap.ecosystem_for("package.json") == "npm"
    assert snap.ecosystem_for("requirements.txt") == "pypi"
    assert snap.ecosystem_for("composer.json") == "packagist"
    assert snap.ecosystem_for("Cargo.toml") == "crates"
    assert snap.ecosystem_for("Gemfile") == "rubygems"
    assert snap.ecosystem_for("src/main.py") is None


def test_snapshot_end_to_end(git_repo):
    (git_repo / "src" / "auth.py").write_text(
        "def login(user, password):\n    return 'SELECT * FROM users'\n")
    (git_repo / "package.json").write_text('{\n  "dependencies": {\n    "left-pad": "^1.0.0"\n  }\n}\n')
    git(git_repo, "add", "-A")

    result = run_script("diff_snapshot", "--staged", cwd=git_repo)
    assert result.returncode == 0
    manifest = json.loads(result.stdout)

    assert manifest["totals"]["files"] == 2
    assert (git_repo / ".swiss-cheese" / "runs" / "latest" / "diff.patch").exists()
    saved = json.loads((git_repo / ".swiss-cheese" / "runs" / "latest" / "manifest.json").read_text())
    assert saved["totals"] == manifest["totals"]

    # dependency manifest detected with ecosystem
    ecos = {d["ecosystem"] for d in manifest["dependency_manifests"]}
    assert "npm" in ecos
    # content flags surfaced for the selector (SELECT ... FROM in added lines)
    assert manifest["flags"]["risky_lines"]
    # no agent selection here anymore — that's select_agents.py's job
    assert "recommended_reviews" not in manifest
    assert manifest["redacted_diff_path"] is None


def test_categories_include_security_and_deps(git_repo):
    (git_repo / "src" / "auth.py").write_text("def f():\n    return 1\n")
    git(git_repo, "add", "-A")
    manifest = json.loads(run_script("diff_snapshot", "--staged", cwd=git_repo).stdout)
    cats = {tuple(f["categories"]) for f in manifest["files"]}
    assert any("security" in c for c in cats)


def test_snapshot_empty_diff(git_repo):
    result = run_script("diff_snapshot", cwd=git_repo)
    assert result.returncode == 0
    assert json.loads(result.stdout)["empty"] is True
