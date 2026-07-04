#!/usr/bin/env python3
"""hook_gate.py — the "agent hooks" Swiss Cheese layer (PostToolUse).

Registered by the plugin as a PostToolUse hook on Write|Edit. It is a silent
no-op unless the current project has opted in via .swiss-cheese/config.json
with a layer like:

    {"id": "agent-hooks", "type": "hook", "enabled": true,
     "on_edit": {".py": "ruff check --quiet {file}",
                 ".ts": "npx tsc --noEmit {file}"}}

On check failure it exits with code 2 and prints the (truncated) tool output
to stderr, which Claude Code feeds back to the agent — the defect is caught
seconds after the edit, not at review time. Internal errors never block the
session (exit 0): the layer has holes by design; other layers cover them.
"""

import json
import os
import subprocess
import sys


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    cwd = payload.get("cwd") or os.getcwd()
    cfg_path = os.path.join(cwd, ".swiss-cheese", "config.json")
    if not os.path.exists(cfg_path):
        sys.exit(0)

    try:
        cfg = json.load(open(cfg_path, encoding="utf-8"))
    except Exception:
        sys.exit(0)

    layer = next((l for l in cfg.get("layers", [])
                  if l.get("id") == "agent-hooks" and l.get("enabled", True)), None)
    if not layer or not isinstance(layer.get("on_edit"), dict):
        sys.exit(0)

    file_path = (payload.get("tool_input") or {}).get("file_path", "")
    ext = os.path.splitext(file_path)[1].lower()
    template = layer["on_edit"].get(ext)
    if not template or not os.path.exists(file_path):
        sys.exit(0)

    cmd = template.replace("{file}", f'"{file_path}"')
    try:
        proc = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True,
                              text=True, timeout=layer.get("timeout", 60))
    except Exception:
        sys.exit(0)

    if proc.returncode != 0:
        tail = (proc.stdout + "\n" + proc.stderr).strip().splitlines()[-25:]
        sys.stderr.write(
            f"[swiss-cheese agent-hooks layer] check failed for {file_path}:\n"
            + "\n".join(tail)
            + "\nFix this before moving on."
        )
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
