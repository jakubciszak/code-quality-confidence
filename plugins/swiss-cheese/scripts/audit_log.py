#!/usr/bin/env python3
"""audit_log.py — append-only audit trail split by harness observability.

Writes JSONL to .swiss-cheese/audit/YYYY-MM.jsonl. No tokens, no cost — the
plugin never reads this back into a model. The design decision is *who writes
which line*:

SYSTEM events (written by a HOOK — zero context, guaranteed complete, the
immutable backbone of the log):
    agent_spawned, layer_result, policy_block, guard_finding

INTERPRETIVE events (written by the MODEL through this script, because only
the model knows the *why*):
    agent_skipped(reason), finding_dismissed

Fail-closed contract: a finding is retired ONLY if a `finding_dismissed`
entry exists for it. `active_findings()` treats any finding without such an
entry as still active — a forgotten log line leaves the finding in force
(visible and safe) rather than silently dropped (invisible and dangerous).

Stdlib only. Every internal error is swallowed on the CLI path (exit 0) — the
audit layer must never kill the session.
"""

import argparse
import json
import os
import sys
import time

SYSTEM_EVENTS = {"agent_spawned", "layer_result", "policy_block", "guard_finding"}
INTERPRETIVE_EVENTS = {"agent_skipped", "finding_dismissed"}


def _month_file(audit_dir, ts):
    month = time.strftime("%Y-%m", time.gmtime(ts))
    return os.path.join(audit_dir, f"{month}.jsonl")


def append_event(audit_dir, event, fields=None, ts=None):
    """Append one event line. Returns the written record."""
    ts = time.time() if ts is None else ts
    os.makedirs(audit_dir, exist_ok=True)
    record = {"ts": round(ts, 3),
              "iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts)),
              "event": event}
    if fields:
        record.update(fields)
    with open(_month_file(audit_dir, ts), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, separators=(",", ":")) + "\n")
    return record


def read_events(audit_dir):
    """Yield every event record across all monthly files (chronological-ish)."""
    if not os.path.isdir(audit_dir):
        return
    for name in sorted(os.listdir(audit_dir)):
        if not name.endswith(".jsonl"):
            continue
        for line in open(os.path.join(audit_dir, name), encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception:
                continue


def dismissed_finding_ids(audit_dir):
    """Set of finding ids that have a recorded finding_dismissed entry."""
    return {e.get("finding_id") for e in read_events(audit_dir)
            if e.get("event") == "finding_dismissed" and e.get("finding_id")}


def active_findings(audit_dir, finding_ids):
    """Findings still in force: those WITHOUT a finding_dismissed entry.

    Fail-closed: absence of a dismissal keeps the finding active.
    """
    dismissed = dismissed_finding_ids(audit_dir)
    return [fid for fid in finding_ids if fid not in dismissed]


def _parse_data(raw):
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        # k=v,k=v fallback
        out = {}
        for pair in raw.split(","):
            if "=" in pair:
                k, v = pair.split("=", 1)
                out[k.strip()] = v.strip()
        return out


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_log = sub.add_parser("log")
    p_log.add_argument("--event", required=True)
    p_log.add_argument("--audit-dir", default=".swiss-cheese/audit")
    p_log.add_argument("--data", help="JSON object or k=v,k=v of extra fields")

    p_dis = sub.add_parser("dismiss")
    p_dis.add_argument("--finding-id", required=True)
    p_dis.add_argument("--reason", required=True)
    p_dis.add_argument("--audit-dir", default=".swiss-cheese/audit")

    p_skip = sub.add_parser("skip")
    p_skip.add_argument("--agent", required=True)
    p_skip.add_argument("--reason", required=True)
    p_skip.add_argument("--audit-dir", default=".swiss-cheese/audit")

    p_active = sub.add_parser("active")
    p_active.add_argument("--finding-ids", required=True, help="comma-separated ids")
    p_active.add_argument("--audit-dir", default=".swiss-cheese/audit")

    args = ap.parse_args()
    try:
        if args.cmd == "log":
            rec = append_event(args.audit_dir, args.event, _parse_data(args.data))
            json.dump(rec, sys.stdout, separators=(",", ":"))
            print()
        elif args.cmd == "dismiss":
            rec = append_event(args.audit_dir, "finding_dismissed",
                               {"finding_id": args.finding_id, "reason": args.reason})
            json.dump(rec, sys.stdout, separators=(",", ":"))
            print()
        elif args.cmd == "skip":
            rec = append_event(args.audit_dir, "agent_skipped",
                               {"agent": args.agent, "reason": args.reason})
            json.dump(rec, sys.stdout, separators=(",", ":"))
            print()
        elif args.cmd == "active":
            ids = [i for i in args.finding_ids.split(",") if i]
            act = active_findings(args.audit_dir, ids)
            json.dump({"active": act, "dismissed": [i for i in ids if i not in act]},
                      sys.stdout, separators=(",", ":"))
            print()
    except Exception as exc:  # audit must never kill the session
        json.dump({"error": str(exc)}, sys.stdout)
        print()
        sys.exit(0)


if __name__ == "__main__":
    main()
