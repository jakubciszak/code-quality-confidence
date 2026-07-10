#!/usr/bin/env python3
"""guard_hook.py — PreToolUse entrypoint for the deterministic guard layer.

Registered as a PreToolUse hook on Bash. It fires the blocking guards only on
commit-like Bash commands, so the hard stop (exit 2) is enforced by the
harness with no model in the loop and no token cost. It is a silent no-op
unless:
  - a .swiss-cheese/config.json exists, AND
  - the `guards` layer mode is `auto`, AND
  - a fresh run snapshot exists (or can be built), AND
  - run_guards reports `blocked: true`.

Every internal error -> exit 0. A layer may have holes; it must never kill
the session. The heavy lifting stays in run_guards.py (also runnable by the
review/loop skills); this wrapper only decides *whether* to run it and turns
a block into the exit-2 the harness respects.
"""

import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sc_common import load_config  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
# Match a real `git commit` (start of a command or after && / ; / |), but not
# `git commit-tree` and friends. The lookahead sits right after `commit` so a
# following hyphen/word char (commit-tree, commitsomething) is rejected, while
# `git commit -m x` (space, then a flag) is accepted.
COMMIT_RE = re.compile(r"(^|[;&|]\s*)git\s+commit(?![-\w])")


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    cwd = payload.get("cwd") or os.getcwd()
    command = (payload.get("tool_input") or {}).get("command", "")
    if not COMMIT_RE.search(command):
        sys.exit(0)

    cfg_path = os.path.join(cwd, ".swiss-cheese", "config.json")
    if not os.path.exists(cfg_path):
        sys.exit(0)
    try:
        cfg = load_config(cfg_path)
    except Exception:
        sys.exit(0)
    if cfg["layers"].get("guards", {}).get("mode", "auto") != "auto":
        sys.exit(0)

    run_dir = os.path.join(cwd, ".swiss-cheese", "runs", "latest")
    try:
        # Build a fresh snapshot of staged changes, then run the guards.
        subprocess.run([sys.executable, os.path.join(HERE, "diff_snapshot.py"),
                        "--staged", "--out", run_dir],
                       cwd=cwd, capture_output=True, text=True, timeout=60)
        if not os.path.exists(os.path.join(run_dir, "manifest.json")):
            sys.exit(0)
        proc = subprocess.run([sys.executable, os.path.join(HERE, "run_guards.py"),
                               "--run-dir", run_dir, "--config", cfg_path],
                              cwd=cwd, capture_output=True, text=True, timeout=90)
    except Exception:
        sys.exit(0)

    if proc.returncode == 2:
        blockers = _summarize(run_dir, cfg["block_at"])
        sys.stderr.write(
            "[swiss-cheese guards] commit blocked — findings at or above "
            f"'{cfg['block_at']}':\n" + blockers +
            "\nResolve these or set the guards layer to `comment` to override.")
        sys.exit(2)
    sys.exit(0)


def _summarize(run_dir, block_at):
    try:
        from sc_common import sev_at_least
        data = json.load(open(os.path.join(run_dir, "guards.json"), encoding="utf-8"))
        lines = []
        for f in data.get("findings", []):
            if f.get("mode") == "auto" and sev_at_least(f["severity"], block_at):
                loc = f.get("path", "")
                if f.get("line"):
                    loc += f":{f['line']}"
                lines.append(f"  - [{f['severity']}] {f['guard']} {loc}: {f['message']}")
        return "\n".join(lines[:20]) or "  (see .swiss-cheese/runs/latest/guards.json)"
    except Exception:
        return "  (see .swiss-cheese/runs/latest/guards.json)"


if __name__ == "__main__":
    main()
