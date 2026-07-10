import json

from conftest import run_script

# `true`/`false` are portable no-op binaries; `sh -c` keeps binary_on_path happy.
PASS = "sh -c 'exit 0'"
FAIL = "sh -c 'echo boom; exit 1'"


def write_v2(tmp_path, layers, **top):
    d = tmp_path / ".swiss-cheese"
    d.mkdir(exist_ok=True)
    cfg = {"version": 2, "layers": layers}
    cfg.update(top)
    (d / "config.json").write_text(json.dumps(cfg))


def write_v1(tmp_path, layers):
    d = tmp_path / ".swiss-cheese"
    d.mkdir(exist_ok=True)
    (d / "config.json").write_text(json.dumps({"version": 1, "layers": layers}))


# --- v2 status model -------------------------------------------------------

def test_all_auto_pass_is_ok(tmp_path):
    write_v2(tmp_path, {"lint": {"mode": "auto", "command": PASS, "fast": True}})
    result = run_script("check_layers", cwd=tmp_path)
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["ok"] is True
    assert data["results"][0]["status"] == "passed"


def test_ok_counts_only_auto_failed(tmp_path):
    # An auto layer passes; a comment layer fails -> still ok.
    write_v2(tmp_path, {
        "lint": {"mode": "auto", "command": PASS, "fast": True},
        "style": {"mode": "comment", "command": FAIL, "fast": True},
    })
    result = run_script("check_layers", cwd=tmp_path)
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["ok"] is True
    style = next(r for r in data["results"] if r["layer"] == "style")
    assert style["status"] == "failed"


def test_auto_failure_breaks_ok(tmp_path):
    write_v2(tmp_path, {
        "lint": {"mode": "auto", "command": PASS, "fast": True},
        "tests": {"mode": "auto", "command": FAIL, "fast": False},
    })
    result = run_script("check_layers", cwd=tmp_path)
    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["ok"] is False
    tests = next(r for r in data["results"] if r["layer"] == "tests")
    assert tests["status"] == "failed"
    assert "boom" in tests["output_tail"]


def test_missing_binary_is_skipped_never_passed(tmp_path):
    write_v2(tmp_path, {
        "leaks": {"mode": "auto", "command": "gitleaks detect",
                  "binary": "definitely-not-a-real-binary-xyz", "fast": True},
    })
    result = run_script("check_layers", cwd=tmp_path)
    assert result.returncode == 0  # skipped does not fail ok
    entry = json.loads(result.stdout)["results"][0]
    assert entry["status"] == "skipped"
    assert "not on PATH" in entry["reason"]


def test_skip_mode_is_skipped(tmp_path):
    write_v2(tmp_path, {"tests": {"mode": "skip", "command": FAIL}})
    result = run_script("check_layers", cwd=tmp_path)
    assert result.returncode == 0
    assert json.loads(result.stdout)["results"][0]["status"] == "skipped"


def test_fast_flag_skips_slow_layers(tmp_path):
    write_v2(tmp_path, {
        "lint": {"mode": "auto", "command": PASS, "fast": True},
        "tests": {"mode": "auto", "command": FAIL, "fast": False},
    })
    result = run_script("check_layers", "--fast", cwd=tmp_path)
    assert result.returncode == 0
    assert json.loads(result.stdout)["ran"] == ["lint"]


def test_only_filter(tmp_path):
    write_v2(tmp_path, {
        "lint": {"mode": "auto", "command": PASS, "fast": True},
        "typecheck": {"mode": "auto", "command": FAIL, "fast": True},
    })
    result = run_script("check_layers", "--only", "lint", cwd=tmp_path)
    assert result.returncode == 0
    assert json.loads(result.stdout)["ran"] == ["lint"]


def test_block_at_warn_at_echoed(tmp_path):
    write_v2(tmp_path, {"lint": {"mode": "auto", "command": PASS}},
             block_at="blocker", warn_at="low")
    data = json.loads(run_script("check_layers", cwd=tmp_path).stdout)
    assert data["block_at"] == "blocker"
    assert data["warn_at"] == "low"


def test_v2_defaults_when_thresholds_absent(tmp_path):
    write_v2(tmp_path, {"lint": {"mode": "auto", "command": PASS}})
    data = json.loads(run_script("check_layers", cwd=tmp_path).stdout)
    assert data["block_at"] == "high"
    assert data["warn_at"] == "medium"


# --- v1 backward compatibility --------------------------------------------

def test_v1_config_runs_and_carries_notice(tmp_path):
    write_v1(tmp_path, [
        {"id": "lint", "type": "scripted", "command": PASS, "fast": True},
        {"id": "review", "type": "agents", "agents": ["correctness"]},
    ])
    result = run_script("check_layers", cwd=tmp_path)
    assert result.returncode == 0
    data = json.loads(result.stdout)
    # scripted+enabled v1 layer maps to auto and runs; agents layer -> skip
    assert data["results"][0]["layer"] == "lint"
    assert data["results"][0]["status"] == "passed"
    review = next(r for r in data["results"] if r["layer"] == "review")
    assert review["status"] == "skipped"
    assert "v1" in data["notice"]


def test_v1_disabled_layer_is_skipped(tmp_path):
    write_v1(tmp_path, [
        {"id": "tests", "type": "scripted", "command": FAIL, "enabled": False},
    ])
    result = run_script("check_layers", cwd=tmp_path)
    assert result.returncode == 0
    assert json.loads(result.stdout)["results"][0]["status"] == "skipped"


def test_extra_top_level_keys_are_preserved(tmp_path):
    # Downstream scripts read arbitrary top-level keys (slopsquat_online,
    # per-guard `guards` overrides, loop); the loader must not drop them.
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                          / "plugins" / "swiss-cheese" / "scripts"))
    from sc_common import load_config
    write_v2(tmp_path, {"guards": {"mode": "auto"}},
             slopsquat_online=True, guards={"injection": "comment"},
             loop={"order": ["lint"], "max_iterations": 3})
    cfg = load_config(str(tmp_path / ".swiss-cheese" / "config.json"))
    assert cfg["slopsquat_online"] is True
    assert cfg["guards"] == {"injection": "comment"}
    assert cfg["loop"]["max_iterations"] == 3


def test_v1_extra_keys_preserved(tmp_path):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                          / "plugins" / "swiss-cheese" / "scripts"))
    from sc_common import load_config
    d = tmp_path / ".swiss-cheese"
    d.mkdir()
    (d / "config.json").write_text(json.dumps(
        {"version": 1, "risk_profile": "high",
         "layers": [{"id": "lint", "type": "scripted", "command": PASS}]}))
    cfg = load_config(str(d / "config.json"))
    assert cfg["risk_profile"] == "high"
    assert cfg["_notice"]  # still nudges to re-init


def test_missing_config_degrades_not_explodes(tmp_path):
    result = run_script("check_layers", cwd=tmp_path)
    # No config -> defaults, no layers, ok=True, exit 0 (never kills session).
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["ok"] is True
    assert data["ran"] == []
