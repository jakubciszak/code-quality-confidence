import json

from conftest import run_script

PASS = "sh -c 'exit 0'"
FAIL = "sh -c 'echo boom; exit 1'"


def _config(tmp_path, commit_gate, layer_cmd):
    d = tmp_path / ".swiss-cheese"
    d.mkdir(exist_ok=True)
    cfg = {"version": 2, "block_at": "high", "warn_at": "medium",
           "layers": {"lint": {"mode": "auto", "command": layer_cmd, "fast": True}}}
    if commit_gate is not None:
        cfg["commit_gate"] = commit_gate
    (d / "config.json").write_text(json.dumps(cfg))


def _payload(cwd, command):
    return json.dumps({"cwd": str(cwd), "tool_input": {"command": command}})


def test_noop_without_config(tmp_path):
    r = run_script("commit_gate", stdin=_payload(tmp_path, "git commit -m x"), cwd=tmp_path)
    assert r.returncode == 0
    assert r.stderr == ""


def test_noop_when_commit_gate_absent(tmp_path):
    _config(tmp_path, None, FAIL)  # layers red, but gate not opted in
    r = run_script("commit_gate", stdin=_payload(tmp_path, "git commit -m x"), cwd=tmp_path)
    assert r.returncode == 0
    assert r.stderr == ""  # silent no-op


def test_warn_mode_reminds_but_exits_zero(tmp_path):
    _config(tmp_path, "warn", FAIL)
    r = run_script("commit_gate", stdin=_payload(tmp_path, "git commit -m x"), cwd=tmp_path)
    assert r.returncode == 0
    assert "red" in r.stderr and "reminder" in r.stderr


def test_block_mode_blocks_on_red(tmp_path):
    _config(tmp_path, "block", FAIL)
    r = run_script("commit_gate", stdin=_payload(tmp_path, "git commit -m x"), cwd=tmp_path)
    assert r.returncode == 2
    assert "blocked" in r.stderr.lower()


def test_block_mode_passes_when_green(tmp_path):
    _config(tmp_path, "block", PASS)
    r = run_script("commit_gate", stdin=_payload(tmp_path, "git commit -m x"), cwd=tmp_path)
    assert r.returncode == 0


def test_does_not_match_commit_tree(tmp_path):
    _config(tmp_path, "block", FAIL)
    r = run_script("commit_gate", stdin=_payload(tmp_path, "git commit-tree abc123"), cwd=tmp_path)
    assert r.returncode == 0  # not a real commit -> gate skips


def test_matches_commit_with_flags(tmp_path):
    _config(tmp_path, "block", FAIL)
    r = run_script("commit_gate", stdin=_payload(tmp_path, 'git commit -am "msg"'), cwd=tmp_path)
    assert r.returncode == 2


def test_ignores_non_commit_bash(tmp_path):
    _config(tmp_path, "block", FAIL)
    r = run_script("commit_gate", stdin=_payload(tmp_path, "git status"), cwd=tmp_path)
    assert r.returncode == 0
