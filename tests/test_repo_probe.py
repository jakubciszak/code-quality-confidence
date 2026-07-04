import json

from conftest import load_script, run_script

probe = load_script("repo_probe")


def test_exists_any_matches_literal_paths(tmp_path):
    (tmp_path / "pyproject.toml").touch()
    assert probe.exists_any(str(tmp_path), ["pyproject.toml", "go.mod"]) == ["pyproject.toml"]


def test_exists_any_matches_wildcard_patterns(tmp_path):
    (tmp_path / "MyApp.csproj").touch()
    assert probe.exists_any(str(tmp_path), ["*.csproj"]) == ["*.csproj"]
    assert probe.exists_any(str(tmp_path), ["*.gemspec"]) == []


def test_probe_end_to_end(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("x = 1\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_app.py").write_text("def test_x(): pass\n")
    (tmp_path / "docs" / "adr").mkdir(parents=True)
    (tmp_path / "docs" / "adr" / "0001-init.md").write_text("# 1. Init\n")
    (tmp_path / "README.md").write_text("# hi\n")
    (tmp_path / "pyproject.toml").write_text("[tool.ruff]\n")

    result = run_script("repo_probe", str(tmp_path))
    assert result.returncode == 0
    data = json.loads(result.stdout)

    assert data["languages"][0]["lang"] == "python"
    assert data["tests"]["has_tests"] is True
    assert data["dependency_manifests"] == ["pyproject.toml"]
    assert data["adr"] == [{"dir": "docs/adr", "count": 1}]
    assert "README.md" in data["docs"]
    assert data["swiss_cheese"]["initialized"] is False
    assert "ruff" in data["linters"]


def test_probe_detects_swiss_cheese_config(tmp_path):
    (tmp_path / ".swiss-cheese").mkdir()
    (tmp_path / ".swiss-cheese" / "config.json").write_text(json.dumps(
        {"layers": [{"id": "lint", "type": "scripted", "enabled": True}]}))

    data = json.loads(run_script("repo_probe", str(tmp_path)).stdout)
    assert data["swiss_cheese"]["initialized"] is True
    assert data["swiss_cheese"]["layers"] == [
        {"id": "lint", "type": "scripted", "enabled": True}]
