"""high_risk guard — flag changes under configured high-risk paths.

Any changed path matching `high_risk_paths` (auth, payments, migrations, ...)
produces a finding. run_guards aggregates these into `escalate: true`, which
the review orchestrator (Phase 4) turns into a full fan-out plus model
escalation to Opus for the architecture/staff lenses.
"""

from . import finding, path_matches

NAME = "high_risk"


def scan(ctx):
    high_risk = ctx.config.get("high_risk_paths", []) or []
    if not high_risk:
        return []
    findings = []
    for f in ctx.files:
        if path_matches(f.get("path", ""), high_risk):
            findings.append(finding(
                NAME, "high",
                f"change under high-risk path {f['path']} — escalate review",
                path=f["path"]))
    return findings
