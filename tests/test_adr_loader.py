import json

from conftest import load_script, run_script

adr = load_script("adr_loader")


def _make_run(tmp_path, diff_text, files):
    run_dir = tmp_path / ".swiss-cheese" / "runs" / "latest"
    run_dir.mkdir(parents=True)
    (run_dir / "diff.redacted.patch").write_text(diff_text)
    (run_dir / "manifest.json").write_text(json.dumps({"files": files}))
    return run_dir


def test_ranks_relevant_adr_first(tmp_path):
    adr_dir = tmp_path / "docs" / "adr"
    adr_dir.mkdir(parents=True)
    (adr_dir / "0001-auth.md").write_text(
        "# Authentication strategy\nWe use session tokens and permission checks "
        "for authorization across handlers.\n")
    (adr_dir / "0002-caching.md").write_text(
        "# Caching layer\nWe use a redis cache with ttl eviction for query results.\n")

    diff = ("+++ b/src/auth/login.py\n"
            "+def login(session, permission, authorization, tokens):\n"
            "+    return check_permission(session)\n")
    _make_run(tmp_path, diff, [{"path": "src/auth/login.py"}])

    top = adr.rank(str(tmp_path), "docs/adr",
                   adr.diff_tokens(str(tmp_path / ".swiss-cheese/runs/latest")), 3)
    assert top[0]["path"] == "docs/adr/0001-auth.md"
    assert top[0]["score"] > 0


def test_returns_top_n_paths_only(tmp_path):
    adr_dir = tmp_path / "docs" / "adr"
    adr_dir.mkdir(parents=True)
    for i in range(5):
        (adr_dir / f"{i:04d}-x.md").write_text(
            f"# ADR {i}\nsomething about payment billing invoice charge {i}\n")
    diff = "+++ b/src/payment/charge.py\n+def charge(payment, billing, invoice):\n"
    _make_run(tmp_path, diff, [{"path": "src/payment/charge.py"}])
    dtokens = adr.diff_tokens(str(tmp_path / ".swiss-cheese/runs/latest"))
    top = adr.rank(str(tmp_path), "docs/adr", dtokens, 2)
    assert len(top) == 2
    assert all("path" in e and "score" in e for e in top)


def test_find_adr_dir_autodetect(tmp_path):
    (tmp_path / "docs" / "decisions").mkdir(parents=True)
    assert adr.find_adr_dir(str(tmp_path), None) == "docs/decisions"


def test_no_adr_dir_returns_empty(tmp_path):
    _make_run(tmp_path, "+++ b/x.py\n+x = 1\n", [{"path": "x.py"}])
    result = run_script("adr_loader", "--repo", str(tmp_path),
                        "--run-dir", str(tmp_path / ".swiss-cheese/runs/latest"),
                        cwd=tmp_path)
    data = json.loads(result.stdout)
    assert data["adr_dir"] is None
    assert data["top"] == []


def test_cli_end_to_end(tmp_path):
    adr_dir = tmp_path / "docs" / "adr"
    adr_dir.mkdir(parents=True)
    (adr_dir / "0001-db.md").write_text(
        "# Database migrations\nAll schema migrations go through the migration runner.\n")
    diff = "+++ b/migrations/003.sql\n+ALTER TABLE users ADD COLUMN migration_flag\n"
    _make_run(tmp_path, diff, [{"path": "migrations/003.sql"}])
    result = run_script("adr_loader", "--repo", str(tmp_path),
                        "--run-dir", str(tmp_path / ".swiss-cheese/runs/latest"),
                        "--top", "1", cwd=tmp_path)
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["adr_dir"] == "docs/adr"
    assert data["top"] and data["top"][0]["path"] == "docs/adr/0001-db.md"
