#!/usr/bin/env python3
"""layer_status.py — render the current defense stack and its holes.

Reads .swiss-cheese/config.json (v2, layers keyed by id with `mode`) plus the
catalog and prints a ready-to-display markdown report: which layers exist,
their mode, and which catalog layers are missing (the aligned-holes risk).
Backward compatible with v1 configs via sc_common.load_config.

Usage:
    python3 layer_status.py [--config .swiss-cheese/config.json] [--json]
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sc_common import load_config  # noqa: E402

CATALOG = [
    ("instructions", "Guardrails in CLAUDE.md / agent instructions"),
    ("lint", "Linting & static analysis"),
    ("typecheck", "Type checking"),
    ("tests", "Automated tests"),
    ("guards", "Deterministic pre-LLM guards (injection, secrets, policy, slopsquat)"),
    ("gitleaks", "Secrets scanning"),
    ("agent-hooks", "Post-edit hook checks (instant feedback)"),
    ("review", "Multi-lens agent code review"),
    ("docs", "Documentation & ADR discipline"),
    ("human-review", "Human review with context"),
]

MODE_ICON = {"auto": "🟢 auto", "comment": "🟡 comment", "skip": "⚪ skip"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=".swiss-cheese/config.json")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if not os.path.exists(args.config):
        print("Swiss Cheese is **not initialized** in this repository. "
              "Run `/swiss-cheese:init` to analyze the repo and set up defense layers.")
        sys.exit(0)

    cfg = load_config(args.config)
    layers = cfg["layers"]  # id -> layer dict (mode normalized)

    if args.json:
        json.dump({"block_at": cfg["block_at"], "warn_at": cfg["warn_at"],
                   "layers": layers,
                   "missing": [c for c, _ in CATALOG if c not in layers]},
                  sys.stdout, separators=(",", ":"))
        print()
        return

    lines = ["# Swiss Cheese — defense stack", "",
             f"Gating: block at **{cfg['block_at']}**, warn at **{cfg['warn_at']}**", ""]
    if cfg.get("_notice"):
        lines += [f"> {cfg['_notice']}", ""]
    lines += ["| Layer | Mode | Detail | Named holes |", "|---|---|---|---|"]
    for lid, layer in layers.items():
        mode = MODE_ICON.get(layer.get("mode", "auto"), layer.get("mode", ""))
        detail = layer.get("command") or layer.get("type") or layer.get("notes", "") or ""
        holes = (layer.get("holes", "") or "")[:60]
        lines.append(f"| {lid} | {mode} | {str(detail)[:50]} | {holes} |")

    missing = [(cid, desc) for cid, desc in CATALOG if cid not in layers]
    if missing:
        lines += ["", "## Holes in the cheese (missing catalog layers)", ""]
        for cid, desc in missing:
            lines.append(f"- **{cid}** — {desc}")
        lines += ["", "_A missing layer is fine if a neighbor covers its holes; review "
                  "whether these gaps align. Add layers with `/swiss-cheese:layer add <id>`._"]
    print("\n".join(lines))


if __name__ == "__main__":
    main()
