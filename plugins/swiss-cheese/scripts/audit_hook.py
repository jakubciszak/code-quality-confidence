#!/usr/bin/env python3
"""audit_hook.py — writes SYSTEM audit events the harness CAN observe.

Registered as a PostToolUse hook. The harness sees these events directly, so
a hook (not the model) records them: the backbone of the audit log is
complete and uninterpreted by construction. Currently records:

  agent_spawned  — a Task tool (subagent) started

Silent no-op unless a `.swiss-cheese/` dir exists in the cwd. Every internal
error -> exit 0; the audit layer must never kill the session.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit_log import append_event  # noqa: E402


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    cwd = payload.get("cwd") or os.getcwd()
    audit_dir = os.path.join(cwd, ".swiss-cheese", "audit")
    if not os.path.isdir(os.path.join(cwd, ".swiss-cheese")):
        sys.exit(0)

    tool = payload.get("tool_name") or payload.get("tool") or ""
    if tool == "Task":
        ti = payload.get("tool_input") or {}
        try:
            append_event(audit_dir, "agent_spawned",
                         {"subagent_type": ti.get("subagent_type", ""),
                          "description": ti.get("description", "")[:80]})
        except Exception:
            pass
    sys.exit(0)


if __name__ == "__main__":
    main()
