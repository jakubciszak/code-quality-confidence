import json

from conftest import run_script


def test_prints_deny_stanza(tmp_path):
    r = run_script("permissions_stanza", cwd=tmp_path)
    assert r.returncode == 0
    data = json.loads(r.stdout)
    deny = data["permissions"]["deny"]
    assert any(".env" in rule for rule in deny)


def test_never_writes_settings(tmp_path):
    # A settings file must be untouched (and none created) by the generator.
    claude = tmp_path / ".claude"
    claude.mkdir()
    settings = claude / "settings.json"
    settings.write_text('{"existing": true}')
    run_script("permissions_stanza", cwd=tmp_path)
    # unchanged
    assert json.loads(settings.read_text()) == {"existing": True}


def test_no_settings_file_created(tmp_path):
    run_script("permissions_stanza", cwd=tmp_path)
    assert not (tmp_path / ".claude" / "settings.json").exists()
    assert not (tmp_path / ".claude").exists()


def test_extra_deny_rules_appended(tmp_path):
    r = run_script("permissions_stanza", "--deny", "Read(./secrets/**)", cwd=tmp_path)
    deny = json.loads(r.stdout)["permissions"]["deny"]
    assert "Read(./secrets/**)" in deny


def test_reminder_goes_to_stderr(tmp_path):
    r = run_script("permissions_stanza", cwd=tmp_path)
    assert "DO NOT write" in r.stderr
