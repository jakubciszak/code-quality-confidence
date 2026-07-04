import json

from conftest import run_script


def write_config(tmp_path, layers, loop=None):
    d = tmp_path / ".swiss-cheese"
    d.mkdir(exist_ok=True)
    cfg = {"version": 1, "risk_profile": "high", "layers": layers}
    if loop:
        cfg["loop"] = loop
    (d / "config.json").write_text(json.dumps(cfg))


def test_uninitialized_message(tmp_path):
    result = run_script("layer_status", cwd=tmp_path)
    assert result.returncode == 0
    assert "not initialized" in result.stdout
    assert "/swiss-cheese:init" in result.stdout


def test_status_table_and_missing_layers(tmp_path):
    write_config(tmp_path, [
        {"id": "lint", "type": "scripted", "enabled": True, "command": "ruff check ."},
        {"id": "review", "type": "agents", "enabled": False, "agents": ["correctness"]},
    ], loop={"order": ["lint", "review"], "max_iterations": 3})
    result = run_script("layer_status", cwd=tmp_path)
    out = result.stdout
    assert result.returncode == 0
    assert "risk profile" in out.lower() and "high" in out
    assert "ruff check ." in out
    assert "❌ disabled" in out
    # layers absent from config are listed as holes
    assert "Holes in the cheese" in out
    assert "**tests**" in out
    assert "lint → review" in out


def test_json_mode(tmp_path):
    write_config(tmp_path, [{"id": "lint", "type": "scripted", "enabled": True,
                             "command": "ruff check ."}])
    result = run_script("layer_status", "--json", cwd=tmp_path)
    data = json.loads(result.stdout)
    assert data["layers"][0]["id"] == "lint"
    assert "tests" in data["missing"]
    assert "lint" not in data["missing"]
