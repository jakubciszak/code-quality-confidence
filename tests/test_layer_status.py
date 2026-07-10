import json

from conftest import run_script


def write_v2(tmp_path, layers, **top):
    d = tmp_path / ".swiss-cheese"
    d.mkdir(exist_ok=True)
    cfg = {"version": 2, "layers": layers}
    cfg.update(top)
    (d / "config.json").write_text(json.dumps(cfg))


def test_uninitialized_message(tmp_path):
    result = run_script("layer_status", cwd=tmp_path)
    assert result.returncode == 0
    assert "not initialized" in result.stdout
    assert "/swiss-cheese:init" in result.stdout


def test_status_table_and_missing_layers(tmp_path):
    write_v2(tmp_path, {
        "lint": {"mode": "auto", "command": "ruff check .", "holes": "blind to logic"},
        "review": {"mode": "comment", "type": "agents"},
    }, block_at="high", warn_at="medium")
    result = run_script("layer_status", cwd=tmp_path)
    out = result.stdout
    assert result.returncode == 0
    assert "block at **high**" in out
    assert "ruff check ." in out
    assert "auto" in out and "comment" in out
    # layers absent from config are listed as holes
    assert "Holes in the cheese" in out
    assert "**tests**" in out
    assert "blind to logic" in out


def test_json_mode(tmp_path):
    write_v2(tmp_path, {"lint": {"mode": "auto", "command": "ruff check ."}})
    result = run_script("layer_status", "--json", cwd=tmp_path)
    data = json.loads(result.stdout)
    assert "lint" in data["layers"]
    assert "tests" in data["missing"]
    assert "lint" not in data["missing"]


def test_v1_config_still_renders(tmp_path):
    d = tmp_path / ".swiss-cheese"
    d.mkdir()
    (d / "config.json").write_text(json.dumps({"version": 1, "layers": [
        {"id": "lint", "type": "scripted", "enabled": True, "command": "ruff check ."}]}))
    result = run_script("layer_status", cwd=tmp_path)
    assert result.returncode == 0
    assert "lint" in result.stdout
    assert "v1" in result.stdout  # notice surfaced
