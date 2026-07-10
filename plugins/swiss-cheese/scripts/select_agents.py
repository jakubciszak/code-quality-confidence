#!/usr/bin/env python3
"""select_agents.py — deterministic review-lens selector (the floor).

A PURE function of manifest.json + guards.json. It returns TWO separate
fields, and the separation is the whole point:

    required            an UNREMOVABLE set of lenses, computed by rule. The
                        review skill treats this as read-only — it may add to
                        it, never subtract from it.
    escalation_allowed  whether the skill is permitted to add lenses on top of
                        `required` when the diff *smells* risky beyond what the
                        metrics caught. This is the model's only lever, and it
                        only ever raises vigilance.

Putting the boundary in the data structure (required vs. added) — not in a
prompt that says "please don't remove" — is what makes the floor real.

Rules for `required`:
- code/logic changed          -> core
- code changed with NO tests  -> tests (coverage gap)
- tests changed               -> tests
- docs changed                -> docs
- security paths / risky lines / CI -> security
- API surface changed         -> architecture
- high-risk path (guards)      -> +staff
- >= 8 files changed          -> +staff
- dependency change           -> +security (slopsquat-heavy) +staff
- non-empty diff, nothing else -> core (never empty)

Stdlib only.
"""

import argparse
import json
import os
import sys

# Canonical ordering so `required` is stable and diffable.
LENS_ORDER = ["core", "security", "architecture", "performance", "tests", "docs", "staff"]
ALL_LENSES = set(LENS_ORDER)


def _order(lenses):
    return [name for name in LENS_ORDER if name in lenses]


def select(manifest, guards=None):
    guards = guards or {}
    files = manifest.get("files", [])
    totals = manifest.get("totals", {})
    flags = manifest.get("flags", {})
    dep_manifests = manifest.get("dependency_manifests", [])

    cats = set()
    for f in files:
        cats.update(f.get("categories", []))

    required = set()
    signals = []

    has_code = bool(cats & {"code", "db", "config"})
    tests_changed = "tests" in cats

    if has_code:
        required.add("core")
        signals.append("code/logic changed -> core")
    if has_code and not tests_changed:
        required.add("tests")
        signals.append("code changed with no test changes -> tests (coverage gap)")
    if tests_changed:
        required.add("tests")
        signals.append("tests changed -> tests")
    if "docs" in cats:
        required.add("docs")
        signals.append("docs changed -> docs")
    if cats & {"security", "ci"} or flags.get("risky_lines"):
        required.add("security")
        signals.append("security-sensitive paths / risky lines / CI -> security")

    if flags.get("api_surface_changed"):
        required.add("architecture")
        signals.append("API surface changed -> architecture")

    added = int(totals.get("added", 0))
    if "db" in cats or added > 300:
        required.add("performance")
        signals.append("DB/schema change or large addition -> performance")

    # Escalation drivers.
    escalate = bool(guards.get("escalate")) or any(
        fnd.get("guard") == "high_risk" for fnd in guards.get("findings", []))
    if escalate:
        required.add("staff")
        signals.append("high-risk path (guards) -> staff")

    n_files = int(totals.get("files", len(files)))
    if n_files >= 8:
        required.add("staff")
        signals.append(f"{n_files} files changed (>= 8) -> staff")

    slopsquat_heavy = False
    if "deps" in cats or dep_manifests:
        required.add("security")
        required.add("staff")
        slopsquat_heavy = True
        signals.append("dependency change -> security (slopsquat-heavy) + staff")

    # Never empty for a non-empty diff.
    if not required and files:
        required.add("core")
        signals.append("non-empty diff, no specific signal -> core (floor)")

    return {
        "required": _order(required),
        "escalation_allowed": len(required) < len(ALL_LENSES),
        "slopsquat_heavy": slopsquat_heavy,
        "escalate_model": escalate,  # review skill overrides architecture/staff to Opus
        "signals": signals,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", default=".swiss-cheese/runs/latest")
    args = ap.parse_args()

    try:
        manifest_path = os.path.join(args.run_dir, "manifest.json")
        guards_path = os.path.join(args.run_dir, "guards.json")
        manifest = json.load(open(manifest_path, encoding="utf-8"))
        guards = None
        if os.path.exists(guards_path):
            guards = json.load(open(guards_path, encoding="utf-8"))
        result = select(manifest, guards)
        json.dump(result, sys.stdout, separators=(",", ":"))
        print()
    except Exception as exc:
        # Fail toward MORE review, not less: default to the full lens set.
        json.dump({"required": _order(ALL_LENSES), "escalation_allowed": False,
                   "slopsquat_heavy": True, "escalate_model": True,
                   "error": str(exc)}, sys.stdout)
        print()


if __name__ == "__main__":
    main()
