import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "plugins" / "swiss-cheese" / "scripts"


def load_script(name):
    """Import a plugin script as a module so its functions can be unit-tested."""
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_script(name, *args, cwd=None, stdin=None):
    """Run a plugin script end-to-end the way the plugin commands do."""
    return subprocess.run(
        [sys.executable, str(SCRIPTS / f"{name}.py"), *args],
        capture_output=True, text=True, cwd=cwd, input=stdin, timeout=60,
    )


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, check=True)


@pytest.fixture
def git_repo(tmp_path):
    """A minimal git repo with one committed source file."""
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.email", "test@test")
    git(tmp_path, "config", "user.name", "test")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("def ok():\n    return 1\n")
    (tmp_path / "README.md").write_text("# readme\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "init")
    return tmp_path
