import json

from conftest import load_script, run_script

rd = load_script("runner_detector")


def test_makefile_wins_priority(tmp_path):
    (tmp_path / "Makefile").write_text("test:\n\tpytest\n\nlint:\n\truff check .\n")
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "jest"}}))
    r = rd.resolve(str(tmp_path), "test")
    assert r["command"] == "make test"
    assert r["via"] == "Makefile"
    assert r["confidence"] == "high"
    # package.json script demoted to an alternative
    assert any(a["via"] == "package.json" for a in r["alternatives"])


def test_package_json_scripts(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({
        "scripts": {"test": "vitest", "lint": "eslint ."}}))
    assert rd.resolve(str(tmp_path), "test")["command"] == "npm run test"
    assert rd.resolve(str(tmp_path), "lint")["command"] == "npm run lint"


def test_composer_scripts(tmp_path):
    (tmp_path / "composer.json").write_text(json.dumps({
        "scripts": {"test": "phpunit"}}))
    r = rd.resolve(str(tmp_path), "test")
    assert r["via"] == "composer.json"
    assert r["command"] == "composer test"


def test_pyproject_tox(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[tool.tox]\nlegacy_tox_ini = ''\n")
    (tmp_path / "tox.ini").write_text("[tox]\nenvlist = py312\n")
    r = rd.resolve(str(tmp_path), "test")
    assert r["command"] == "tox"
    assert r["via"] == "pyproject.toml"


def test_poetry_script(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        "[tool.poetry]\nname='x'\n\n[tool.poetry.scripts]\ntest='x:test'\n")
    r = rd.resolve(str(tmp_path), "test")
    assert r["command"] == "poetry run test"


def test_justfile_recipes(tmp_path):
    (tmp_path / "justfile").write_text("test:\n    pytest\n\nlint:\n    ruff check .\n")
    assert rd.resolve(str(tmp_path), "lint")["command"] == "just lint"


def test_taskfile_tasks(tmp_path):
    (tmp_path / "Taskfile.yml").write_text(
        "version: '3'\ntasks:\n  test:\n    cmds:\n      - pytest\n  build:\n    cmds:\n      - go build\n")
    assert rd.resolve(str(tmp_path), "test")["command"] == "task test"
    assert rd.resolve(str(tmp_path), "build")["command"] == "task build"


def test_compose_fallback_low_confidence(tmp_path):
    (tmp_path / "docker-compose.yml").write_text(
        "services:\n  app:\n    image: x\n  db:\n    image: y\n")
    # include_path=False so a globally-installed pytest/mypy doesn't pre-empt
    # the compose fallback in the CI toolbox.
    r = rd.resolve(str(tmp_path), "test", include_path=False)
    assert r["via"] == "docker-compose.yml"
    assert r["confidence"] == "low"


def test_no_runner_returns_none(tmp_path):
    # Nothing in the repo and PATH ignored -> genuinely no runner.
    assert rd.resolve(str(tmp_path), "typecheck", include_path=False) is None


def test_local_binary_beats_path(tmp_path):
    binp = tmp_path / "node_modules" / ".bin"
    binp.mkdir(parents=True)
    (binp / "eslint").write_text("#!/bin/sh\n")
    r = rd.resolve(str(tmp_path), "lint")  # include_path default True
    # even if ruff is on PATH, the repo-local eslint wins
    assert r["via"] == "binary"
    assert r["command"] == "node_modules/.bin/eslint"
    assert r["confidence"] == "high"


def test_high_risk_paths_probe(tmp_path):
    (tmp_path / "src" / "auth").mkdir(parents=True)
    (tmp_path / "migrations").mkdir()
    (tmp_path / "src" / "payments").mkdir()
    (tmp_path / "src" / "utils").mkdir()
    paths = rd.propose_high_risk_paths(str(tmp_path))
    assert "src/auth/**" in paths
    assert "migrations/**" in paths
    assert "src/payments/**" in paths
    assert not any("utils" in p for p in paths)


def test_end_to_end_writes_runners_json(tmp_path):
    (tmp_path / "Makefile").write_text("test:\n\tpytest\n")
    (tmp_path / "src" / "auth").mkdir(parents=True)
    result = run_script("runner_detector", str(tmp_path), cwd=tmp_path)
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["runners"]["test"]["command"] == "make test"
    assert "src/auth/**" in data["high_risk_paths"]
    saved = json.loads((tmp_path / ".swiss-cheese" / "runners.json").read_text())
    assert saved["runners"] == data["runners"]
