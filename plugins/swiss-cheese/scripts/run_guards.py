#!/usr/bin/env python3
"""run_guards.py — run the deterministic pre-LLM guard layer over a run dir.

Reads <run-dir>/diff.patch + manifest.json, runs each guard, and writes
<run-dir>/guards.json (findings + escalate + blocked). The secrets guard also
yields a redacted diff, always written to <run-dir>/diff.redacted.patch so
review subagents can be handed a secret-free artifact.

Usage:
    run_guards.py --run-dir .swiss-cheese/runs/latest [--only injection,policy]
                  [--config .swiss-cheese/config.json] [--online]

Exit code:
    2  a finding reaches `block_at` AND its guard is in `auto` mode
    0  otherwise — INCLUDING any internal error (a layer may have holes, but
       it must never kill the session)

Stdlib only.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sc_common import load_config, sev_at_least  # noqa: E402
from guards import injection, secrets, policy, slopsquat, high_risk  # noqa: E402

GUARDS = {
    "injection": injection,
    "secrets": secrets,
    "policy": policy,
    "slopsquat": slopsquat,
    "high_risk": high_risk,
}


class Ctx:
    """Everything a guard needs — the diff is data, never executed."""
    def __init__(self, run_dir, diff_text, manifest, config, online):
        self.run_dir = run_dir
        self.diff_text = diff_text
        self.manifest = manifest
        self.files = manifest.get("files", [])
        self.config = config
        self.online = online
        self.redacted_diff_text = diff_text  # secrets guard may replace this
        self.secrets_redacted = 0


def guard_mode(config, guard_name):
    """Resolve a guard's mode: per-guard override -> `guards` layer -> auto."""
    overrides = config.get("guards") if isinstance(config.get("guards"), dict) else {}
    if guard_name in overrides:
        return overrides[guard_name]
    layer = config["layers"].get("guards", {})
    return layer.get("mode", "auto")


def run(run_dir, only, config, online):
    diff_path = os.path.join(run_dir, "diff.patch")
    manifest_path = os.path.join(run_dir, "manifest.json")
    with open(diff_path, encoding="utf-8") as fh:
        diff_text = fh.read()
    with open(manifest_path, encoding="utf-8") as fh:
        manifest = json.load(fh)

    ctx = Ctx(run_dir, diff_text, manifest, config, online)
    selected = only or list(GUARDS)

    findings, escalate, blocked = [], False, False
    for name in selected:
        guard = GUARDS.get(name)
        if guard is None:
            continue
        mode = guard_mode(config, name)
        if mode == "skip":
            continue
        try:
            results = guard.scan(ctx)
        except Exception as exc:  # a guard may have holes; keep the others alive
            findings.append({"guard": name, "severity": "low",
                             "message": f"guard errored (skipped): {exc}"})
            continue
        for f in results:
            f["mode"] = mode
            findings.append(f)
            if name == "high_risk":
                escalate = True
            if mode == "auto" and sev_at_least(f["severity"], config["block_at"]):
                blocked = True

    # Always write a redacted diff so downstream review never touches raw.
    redacted_path = os.path.join(run_dir, "diff.redacted.patch")
    with open(redacted_path, "w", encoding="utf-8") as fh:
        fh.write(ctx.redacted_diff_text)
    manifest["redacted_diff_path"] = os.path.abspath(redacted_path)
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1)

    guards_json = {
        "block_at": config["block_at"],
        "warn_at": config["warn_at"],
        "blocked": blocked,
        "escalate": escalate,
        "secrets_redacted": ctx.secrets_redacted,
        "redacted_diff_path": os.path.abspath(redacted_path),
        "findings": findings,
    }
    with open(os.path.join(run_dir, "guards.json"), "w", encoding="utf-8") as fh:
        json.dump(guards_json, fh, indent=1)

    # Backbone audit events: guard findings are deterministic, so a script
    # (not the model) records them. Best-effort — audit never blocks review.
    try:
        from audit_log import append_event
        # run_dir is conventionally .swiss-cheese/runs/<id>; audit sits at
        # .swiss-cheese/audit (two levels up from run_dir).
        audit_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(run_dir))), "audit")
        for f in findings:
            append_event(audit_dir, "guard_finding",
                         {"guard": f["guard"], "severity": f["severity"],
                          "path": f.get("path"), "finding_id": finding_id(f)})
        if blocked:
            append_event(audit_dir, "policy_block", {"block_at": config["block_at"]})
    except Exception:
        pass
    return guards_json


def finding_id(f):
    """Stable id for a guard finding (for dismissal / active tracking)."""
    return f"{f.get('guard')}:{f.get('path', '')}:{f.get('line', '')}:{f.get('severity')}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", default=".swiss-cheese/runs/latest")
    ap.add_argument("--only")
    ap.add_argument("--config", default=".swiss-cheese/config.json")
    ap.add_argument("--online", action="store_true")
    args = ap.parse_args()

    try:
        config = load_config(args.config)
        online = args.online or bool(config.get("slopsquat_online"))
        only = args.only.split(",") if args.only else None
        result = run(args.run_dir, only, config, online)
        json.dump(result, sys.stdout, separators=(",", ":"))
        print()
        sys.exit(2 if result["blocked"] else 0)
    except SystemExit:
        raise
    except Exception as exc:  # never kill the session
        json.dump({"blocked": False, "escalate": False, "findings": [],
                   "error": str(exc)}, sys.stdout)
        print()
        sys.exit(0)


if __name__ == "__main__":
    main()
