"""policy guard — deterministic merge-policy rules over diff size and markers.

Rules (all decided by script, never the model):
- diff >= 2000 changed LOC -> blocker; >= 500 -> medium
- a high-risk path touched without a `human-reviewed` marker -> high
- > 100 changed LOC without an `AI-disclosure` section -> medium
"""

from . import all_added_text, finding, path_matches

NAME = "policy"

HUMAN_MARKER = "human-reviewed"
DISCLOSURE_MARKER = "AI-disclosure"


def scan(ctx):
    findings = []
    totals = ctx.manifest.get("totals", {})
    loc = int(totals.get("added", 0)) + int(totals.get("deleted", 0))

    if loc >= 2000:
        findings.append(finding(
            NAME, "blocker",
            f"diff is {loc} LOC (>= 2000) — too large to review safely; split it"))
    elif loc >= 500:
        findings.append(finding(
            NAME, "medium",
            f"diff is {loc} LOC (>= 500) — large change, expect deeper review"))

    # The two marker checks look at the whole diff text (added lines) plus the
    # raw diff so a marker in an unchanged banner still counts.
    haystack = (all_added_text(ctx.diff_text) + "\n" + ctx.diff_text)
    has_human = HUMAN_MARKER.lower() in haystack.lower()
    has_disclosure = DISCLOSURE_MARKER.lower() in haystack.lower()

    high_risk = ctx.config.get("high_risk_paths", []) or []
    touched_high_risk = [f["path"] for f in ctx.files
                         if path_matches(f.get("path", ""), high_risk)]
    if touched_high_risk and not has_human:
        findings.append(finding(
            NAME, "high",
            f"high-risk path(s) changed without a '{HUMAN_MARKER}' marker: "
            + ", ".join(touched_high_risk[:5]),
            path=touched_high_risk[0]))

    if loc > 100 and not has_disclosure:
        findings.append(finding(
            NAME, "medium",
            f"{loc} LOC changed without an '{DISCLOSURE_MARKER}' section"))

    return findings
