"""The most important test in the plugin: the deterministic review-lens floor.

`required` is a pure function of manifest.json + guards.json and can never be
empty for a non-empty diff. High-risk paths, big diffs, dependency changes and
API-surface changes all raise the floor. The model may only add on top.
"""

import json

from conftest import load_script, run_script

sa = load_script("select_agents")


def manifest(files=None, totals=None, flags=None, deps=None):
    files = files or []
    return {
        "files": files,
        "totals": totals or {"files": len(files),
                             "added": sum(f.get("added", 0) for f in files),
                             "deleted": 0},
        "flags": flags or {"risky_lines": [], "api_surface_changed": False},
        "dependency_manifests": deps or [],
    }


def f(path, cats, added=10, status="M"):
    return {"path": path, "categories": cats, "added": added, "deleted": 0,
            "status": status}


# --- the spec's named cases ------------------------------------------------

def test_migrations_diff_requires_staff():
    m = manifest([f("migrations/003_add.sql", ["db"])],
                 totals={"files": 1, "added": 20})
    guards = {"escalate": True, "findings": [
        {"guard": "high_risk", "severity": "high", "path": "migrations/003_add.sql"}]}
    result = sa.select(m, guards)
    assert "staff" in result["required"]


def test_eight_files_requires_staff():
    files = [f(f"src/m{i}.py", ["code"]) for i in range(8)]
    result = sa.select(manifest(files, totals={"files": 8, "added": 80}))
    assert "staff" in result["required"]


def test_dependency_change_slopsquat_heavy_plus_staff():
    m = manifest([f("package.json", ["deps"])],
                 deps=[{"path": "package.json", "ecosystem": "npm"}])
    result = sa.select(m)
    assert result["slopsquat_heavy"] is True
    assert "staff" in result["required"]
    assert "security" in result["required"]


def test_required_never_empty_for_nonempty_diff():
    # An "other"-only file still yields a floor.
    result = sa.select(manifest([f("Makefile", ["other"])]))
    assert result["required"] == ["core"]


def test_api_surface_change_requires_architecture():
    m = manifest([f("src/api.py", ["code"])],
                 flags={"risky_lines": [], "api_surface_changed": True})
    assert "architecture" in sa.select(m)["required"]


# --- base sets by change type ---------------------------------------------

def test_tests_only_change():
    result = sa.select(manifest([f("tests/test_x.py", ["tests"])]))
    assert result["required"] == ["tests"]


def test_docs_only_change():
    result = sa.select(manifest([f("README.md", ["docs"])]))
    assert result["required"] == ["docs"]


def test_code_without_tests_gets_tests_lens():
    result = sa.select(manifest([f("src/x.py", ["code"])]))
    assert "core" in result["required"]
    assert "tests" in result["required"]  # coverage gap


def test_security_path_requires_security():
    result = sa.select(manifest([f("src/auth/login.py", ["code", "security"])]))
    assert "security" in result["required"]


# --- escalation_allowed semantics -----------------------------------------

def test_escalation_allowed_when_room_to_add():
    result = sa.select(manifest([f("README.md", ["docs"])]))
    assert result["escalation_allowed"] is True


def test_escalation_not_allowed_when_all_lenses_required():
    # Contrive a diff that trips every rule -> nothing left to add.
    files = [f(f"src/auth/m{i}.py", ["code", "security"]) for i in range(8)]
    files.append(f("package.json", ["deps"]))
    files.append(f("migrations/1.sql", ["db"]))   # -> performance
    files.append(f("README.md", ["docs"]))        # -> docs
    m = manifest(files, totals={"files": 11, "added": 400},
                 flags={"risky_lines": ["eval("], "api_surface_changed": True},
                 deps=[{"path": "package.json", "ecosystem": "npm"}])
    guards = {"escalate": True, "findings": [{"guard": "high_risk"}]}
    result = sa.select(m, guards)
    assert set(result["required"]) == sa.ALL_LENSES
    assert result["escalation_allowed"] is False


# --- purity / determinism --------------------------------------------------

def test_selection_is_pure_and_ordered():
    m = manifest([f("src/x.py", ["code"])])
    r1 = sa.select(m)
    r2 = sa.select(m)
    assert r1 == r2
    # canonical ordering
    assert r1["required"] == [l for l in sa.LENS_ORDER if l in r1["required"]]


def test_high_risk_from_findings_without_escalate_flag():
    m = manifest([f("src/billing/charge.py", ["code"])])
    guards = {"findings": [{"guard": "high_risk", "severity": "high"}]}
    assert "staff" in sa.select(m, guards)["required"]


# --- CLI end-to-end --------------------------------------------------------

def test_cli_reads_run_dir(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "manifest.json").write_text(json.dumps(
        manifest([f("migrations/x.sql", ["db"])], totals={"files": 1, "added": 5})))
    (run_dir / "guards.json").write_text(json.dumps(
        {"escalate": True, "findings": [{"guard": "high_risk"}]}))
    result = run_script("select_agents", "--run-dir", str(run_dir), cwd=tmp_path)
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert "staff" in data["required"]


def test_cli_missing_manifest_fails_open_to_full_set(tmp_path):
    result = run_script("select_agents", "--run-dir", str(tmp_path), cwd=tmp_path)
    data = json.loads(result.stdout)
    assert set(data["required"]) == sa.ALL_LENSES  # fail toward more review
