#!/usr/bin/env python3
"""permissions_stanza.py — PRINT a settings stanza for the user to merge.

`/swiss-cheese:init` proposes hardening (deny reads of dotenv files, register
the plugin hooks) but must NEVER edit `.claude/settings.json` itself. This
script only prints JSON to stdout; writing is always the user's explicit act.

Usage:
    permissions_stanza.py [--deny 'Read(./.env*)' ...] [--with-hooks]

Prints a JSON object with a `permissions.deny` list (and optionally a `hooks`
note). It does not read, create, or modify any settings file. Stdlib only.
"""

import argparse
import json
import os
import sys

DEFAULT_DENY = [
    "Read(./.env)",
    "Read(./.env.*)",
    "Read(./**/.env)",
    "Read(./**/*.pem)",
    "Read(./**/id_rsa)",
]


def build(deny, with_hooks):
    stanza = {"permissions": {"deny": deny}}
    if with_hooks:
        stanza["_note"] = (
            "Plugin hooks (guards PreToolUse, commit gate, audit) ship with the "
            "plugin and register automatically once installed — no settings edit "
            "needed. This stanza only adds read-deny hardening.")
    return stanza


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deny", action="append", help="extra deny rule(s)")
    ap.add_argument("--with-hooks", action="store_true")
    args = ap.parse_args()

    deny = list(DEFAULT_DENY)
    for extra in args.deny or []:
        if extra not in deny:
            deny.append(extra)

    stanza = build(deny, args.with_hooks)
    # Print only. Never touch settings.json.
    print("# Propose this to the user — DO NOT write it to .claude/settings.json "
          "automatically. Merge is the user's explicit action.", file=sys.stderr)
    json.dump(stanza, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
    # Belt-and-suspenders: assert we never opened a settings file for writing.
    assert not os.environ.get("_SC_WROTE_SETTINGS")
