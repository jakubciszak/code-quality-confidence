#!/usr/bin/env python3
"""layer_status.py — render the current defense stack and its holes.

Reads .swiss-cheese/config.json plus cheap filesystem probes and prints a
ready-to-display markdown report: which layers exist, which are enabled,
and which catalog layers are missing (the "aligned holes" risk). The agent
displays this output instead of assembling it from many tool calls.

Usage:
    python3 layer_status.py [--config .swiss-cheese/config.json] [--json]
"""

import argparse
import json
import os
import sys

CATALOG = [
    ("instructions", "Guardrails in CLAUDE.md / agent instructions"),
    ("lint", "Linting & static analysis"),
    ("typecheck", "Type checking"),
    ("tests", "Automated tests"),
    ("agent-hooks", "Post-edit hook checks (instant feedback)"),
    ("pre-commit", "Pre-commit hooks"),
    ("secrets-scan", "Secrets & dependency scanning"),
    ("review", "Multi-agent code review"),
    ("ci", "CI pipeline"),
    ("docs", "Documentation & ADR discipline"),
    ("human-review", "Human review with context"),
    ("dynamic-testing", "DAST / chaos / runtime testing (high-risk systems)"),
]

TYPE_ICON = {"scripted": "⚙️ scripted", "agents": "🤖 agents", "hook": "🪝 hook",
             "knowledge": "📘 knowledge", "process": "👤 process", "custom": "🧩 custom"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=".swiss-cheese/config.json")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if not os.path.exists(args.config):
        print("Swiss Cheese is **not initialized** in this repository. "
              "Run `/swiss-cheese:init` to analyze the repo and set up defense layers.")
        sys.exit(0)

    cfg = json.load(open(args.config, encoding="utf-8"))
    layers = cfg.get("layers", [])
    by_id = {l.get("id"): l for l in layers}

    if args.json:
        json.dump({"layers": layers,
                   "missing": [c for c, _ in CATALOG if c not in by_id]},
                  sys.stdout, separators=(",", ":"))
        print()
        return

    lines = ["# Swiss Cheese — defense stack", "",
             f"Risk profile: **{cfg.get('risk_profile', 'standard')}**", "",
             "| Layer | Type | Enabled | Detail |", "|---|---|---|---|"]
    for l in layers:
        detail = l.get("command") or ", ".join(l.get("agents", [])) or l.get("notes", "") or ""
        icon = TYPE_ICON.get(l.get("type", "custom"), l.get("type", ""))
        lines.append(f"| {l.get('id')} | {icon} | {'✅' if l.get('enabled', True) else '❌ disabled'} "
                     f"| {detail[:70]} |")

    missing = [(cid, desc) for cid, desc in CATALOG if cid not in by_id]
    if missing:
        lines += ["", "## Holes in the cheese (missing catalog layers)", ""]
        for cid, desc in missing:
            lines.append(f"- **{cid}** — {desc}")
        lines += ["", "_A missing layer is fine if a neighbor covers its holes; "
                  "review whether these gaps align. Add layers with `/swiss-cheese:layer add <id>`._"]

    loop = cfg.get("loop", {})
    if loop:
        lines += ["", f"Loop order: `{' → '.join(loop.get('order', []))}` "
                  f"(max {loop.get('max_iterations', 5)} iterations)"]
    print("\n".join(lines))


if __name__ == "__main__":
    main()
