"""injection guard — treat the diff as data, flag smuggled instructions.

Scans added diff lines for prompt-injection/control tokens and flags changes
to agent-control files. Patterns live in references/injection-patterns.json
(with an embedded fallback). See references/injection-patterns.md.
"""

from . import finding, iter_added_lines, load_ref_json, path_matches

NAME = "injection"

_FALLBACK = {
    "hard": {"severity": "blocker", "patterns": [
        "ignore previous instructions", "<|im_start|>", "[/INST]",
        "<<SYS>>", "export ANTHROPIC_API_KEY"]},
    "soft": {"severity": "medium", "patterns": [
        "// ai: approve", "trust me", "this is safe because", "don't review"]},
    "control_files": {"severity": "high", "globs": [
        ".claude/**", "CLAUDE.md", "AGENTS.md", ".cursorrules", "*mcp.json"]},
}


def scan(ctx):
    cat = load_ref_json("injection-patterns.json", _FALLBACK)
    findings = []

    hard = cat.get("hard", {})
    soft = cat.get("soft", {})
    hard_pats = [(p, p.lower()) for p in hard.get("patterns", [])]
    soft_pats = [(p, p.lower()) for p in soft.get("patterns", [])]

    for path, lineno, text in iter_added_lines(ctx.diff_text):
        low = text.lower()
        for orig, needle in hard_pats:
            if needle in low:
                findings.append(finding(
                    NAME, hard.get("severity", "blocker"),
                    f"hard prompt-injection token in added code: {orig!r}",
                    path=path, line=lineno, match=text.strip()))
        for orig, needle in soft_pats:
            if needle in low:
                findings.append(finding(
                    NAME, soft.get("severity", "medium"),
                    f"comment-and-control phrasing steering the reviewer: {orig!r}",
                    path=path, line=lineno, match=text.strip()))

    # Agent-control file modification — matched on changed path, not content.
    control = cat.get("control_files", {})
    globs = control.get("globs", [])
    for f in ctx.files:
        if path_matches(f.get("path", ""), globs):
            findings.append(finding(
                NAME, control.get("severity", "high"),
                f"modifies agent-control file {f['path']} — poisons downstream layers",
                path=f["path"]))
    return findings
