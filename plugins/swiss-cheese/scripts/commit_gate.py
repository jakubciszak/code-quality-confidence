#!/usr/bin/env python3
"""commit_gate.py — PreToolUse gate on `git commit` for the scripted layers.

Registered as a PreToolUse hook on Bash. Matches exactly `git commit` (start
of command or after ;/&&/||) but NOT `git commit-tree`. Behavior by config:

    commit_gate absent / "off"      -> silent no-op (exit 0). The layer is off
                                       until the project opts in.
    commit_gate: "warn" (default    -> if check_layers --fast is red, print a
                        when opted)    reminder to stderr and exit 0.
    commit_gate: "block"            -> if check_layers --fast is red, exit 2
                                       (hard block the commit).

Any internal error -> exit 0. A gate may have holes; it must never wedge the
session. Stdlib only.
"""

import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sc_common import load_config  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
# `commit` must not be followed by a hyphen or word char (rejects commit-tree),
# but a following space + flag (`git commit -m x`) is fine.
COMMIT_RE = re.compile(r"(^|[;&|]\s*)git\s+commit(?![-\w])")


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    command = (payload.get("tool_input") or {}).get("command", "")
    if not COMMIT_RE.search(command):
        sys.exit(0)

    cwd = payload.get("cwd") or os.getcwd()
    cfg_path = os.path.join(cwd, ".swiss-cheese", "config.json")
    if not os.path.exists(cfg_path):
        sys.exit(0)

    try:
        cfg = load_config(cfg_path)
    except Exception:
        sys.exit(0)

    mode = cfg.get("commit_gate", "off")
    if mode not in ("warn", "block"):
        sys.exit(0)  # silent no-op until the project turns the layer on

    try:
        proc = subprocess.run(
            [sys.executable, os.path.join(HERE, "check_layers.py"),
             "--fast", "--config", cfg_path],
            cwd=cwd, capture_output=True, text=True, timeout=300)
        result = json.loads(proc.stdout or "{}")
    except Exception:
        sys.exit(0)  # can't run the gate -> don't block

    if result.get("ok", True):
        sys.exit(0)

    failing = [r["layer"] for r in result.get("results", [])
               if r.get("status") == "failed"]
    msg = ("[swiss-cheese commit gate] fast scripted layers are red: "
           + ", ".join(failing) + ".")
    if mode == "block":
        sys.stderr.write(msg + " Commit blocked (commit_gate: block). "
                         "Fix these or run the layers to see details.")
        sys.exit(2)
    sys.stderr.write(msg + " (reminder only — set commit_gate: block to enforce.)")
    sys.exit(0)


if __name__ == "__main__":
    main()
