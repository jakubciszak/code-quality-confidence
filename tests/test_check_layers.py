import json

from conftest import run_script


def write_config(tmp_path, layers):
    d = tmp_path / ".swiss-cheese"
    d.mkdir(exist_ok=True)
    (d / "config.json").write_text(json.dumps({"version": 1, "layers": layers}))


PASS = "python3 -c \"print('ok')\""
FAIL = "python3 -c \"import sys; print('boom'); sys.exit(1)\""


def test_all_layers_pass(tmp_path):
    write_config(tmp_path, [
        {"id": "lint", "type": "scripted", "command": PASS, "fast": True},
        {"id": "review", "type": "agents", "agents": ["correctness"]},  # non-scripted: ignored
    ])
    result = run_script("check_layers", cwd=tmp_path)
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["ok"] is True
    assert data["ran"] == ["lint"]


def test_failing_layer_reports_tail_and_exit_1(tmp_path):
    write_config(tmp_path, [
        {"id": "lint", "type": "scripted", "command": PASS, "fast": True},
        {"id": "tests", "type": "scripted", "command": FAIL, "fast": False},
    ])
    result = run_script("check_layers", cwd=tmp_path)
    assert result.returncode == 1
    data = json.loads(result.stdout)
    failing = next(r for r in data["results"] if r["layer"] == "tests")
    assert failing["ok"] is False
    assert "boom" in failing["output_tail"]


def test_fast_flag_skips_slow_layers(tmp_path):
    write_config(tmp_path, [
        {"id": "lint", "type": "scripted", "command": PASS, "fast": True},
        {"id": "tests", "type": "scripted", "command": FAIL, "fast": False},
    ])
    result = run_script("check_layers", "--fast", cwd=tmp_path)
    assert result.returncode == 0
    assert json.loads(result.stdout)["ran"] == ["lint"]


def test_only_filter(tmp_path):
    write_config(tmp_path, [
        {"id": "lint", "type": "scripted", "command": PASS, "fast": True},
        {"id": "typecheck", "type": "scripted", "command": FAIL, "fast": True},
    ])
    result = run_script("check_layers", "--only", "lint", cwd=tmp_path)
    assert result.returncode == 0
    assert json.loads(result.stdout)["ran"] == ["lint"]


def test_disabled_layer_not_run(tmp_path):
    write_config(tmp_path, [
        {"id": "tests", "type": "scripted", "command": FAIL, "enabled": False},
    ])
    result = run_script("check_layers", cwd=tmp_path)
    assert result.returncode == 0
    assert json.loads(result.stdout)["ran"] == []


def test_missing_config_is_an_error(tmp_path):
    result = run_script("check_layers", cwd=tmp_path)
    assert result.returncode == 1
    assert "init" in json.loads(result.stdout)["error"]
