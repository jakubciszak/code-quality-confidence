import json

from conftest import run_script

CHECK_PY = "python3 -m py_compile {file}"


def write_config(tmp_path, on_edit=None, enabled=True):
    d = tmp_path / ".swiss-cheese"
    d.mkdir(exist_ok=True)
    (d / "config.json").write_text(json.dumps({"layers": [
        {"id": "agent-hooks", "type": "hook", "enabled": enabled,
         "on_edit": on_edit or {".py": CHECK_PY}}]}))


def payload(tmp_path, file_path):
    return json.dumps({"cwd": str(tmp_path), "tool_name": "Edit",
                       "tool_input": {"file_path": file_path}})


def gate(tmp_path, file_path):
    return run_script("hook_gate", stdin=payload(tmp_path, file_path))


def test_noop_without_project_config(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("x = 1\n")
    assert gate(tmp_path, str(f)).returncode == 0


def test_noop_when_layer_disabled(tmp_path):
    write_config(tmp_path, enabled=False)
    f = tmp_path / "a.py"
    f.write_text("def broken(:\n")
    assert gate(tmp_path, str(f)).returncode == 0


def test_noop_for_unmapped_extension(tmp_path):
    write_config(tmp_path)
    f = tmp_path / "a.txt"
    f.write_text("not python\n")
    assert gate(tmp_path, str(f)).returncode == 0


def test_valid_file_passes_silently(tmp_path):
    write_config(tmp_path)
    f = tmp_path / "a.py"
    f.write_text("x = 1\n")
    result = gate(tmp_path, str(f))
    assert result.returncode == 0
    assert result.stderr == ""


def test_failing_check_exits_2_with_feedback(tmp_path):
    write_config(tmp_path)
    f = tmp_path / "a.py"
    f.write_text("def broken(:\n")
    result = gate(tmp_path, str(f))
    assert result.returncode == 2
    assert "agent-hooks layer" in result.stderr
    assert "a.py" in result.stderr


def test_relative_path_resolved_against_payload_cwd(tmp_path):
    write_config(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "bad.py").write_text("def broken(:\n")
    result = gate(tmp_path, "src/bad.py")
    assert result.returncode == 2


def test_shell_metacharacters_in_path_are_quoted(tmp_path):
    write_config(tmp_path)
    weird = tmp_path / "we ird$(name)"
    weird.mkdir()
    good = weird / "ok.py"
    good.write_text("x = 1\n")
    assert gate(tmp_path, str(good)).returncode == 0
    bad = weird / "bad.py"
    bad.write_text("def broken(:\n")
    assert gate(tmp_path, str(bad)).returncode == 2


def test_garbage_stdin_never_blocks(tmp_path):
    assert run_script("hook_gate", stdin="not json at all").returncode == 0


def _write_config_v2(tmp_path, mode="auto"):
    d = tmp_path / ".swiss-cheese"
    d.mkdir(exist_ok=True)
    (d / "config.json").write_text(json.dumps({"version": 2, "layers": {
        "agent-hooks": {"mode": mode, "on_edit": {".py": CHECK_PY}}}}))


def test_v2_config_agent_hooks_fires(tmp_path):
    _write_config_v2(tmp_path)
    f = tmp_path / "a.py"
    f.write_text("def broken(:\n")
    result = gate(tmp_path, str(f))
    assert result.returncode == 2
    assert "agent-hooks layer" in result.stderr


def test_v2_config_skip_mode_is_noop(tmp_path):
    _write_config_v2(tmp_path, mode="skip")
    f = tmp_path / "a.py"
    f.write_text("def broken(:\n")
    assert gate(tmp_path, str(f)).returncode == 0
