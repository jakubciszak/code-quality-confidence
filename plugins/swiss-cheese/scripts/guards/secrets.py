"""secrets guard — detect credentials and redact them out of the diff.

Beyond flagging, this guard produces the redacted diff text that run_guards
writes to `diff.redacted.patch`. From then on, review subagents are handed the
redacted path — a secret must never reach a model's context window.
"""

import re

from . import finding, iter_added_lines

NAME = "secrets"

# (label, severity, compiled regex, group index of the secret value to redact)
_RULES = [
    ("aws-access-key", "blocker", re.compile(r"\b(AKIA[0-9A-Z]{16})\b"), 1),
    ("private-key", "blocker",
     re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC |DSA |PGP )?PRIVATE KEY-----"), 0),
    ("github-token", "high", re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{36,})\b"), 1),
    ("github-pat", "high", re.compile(r"\b(github_pat_[A-Za-z0-9_]{60,})\b"), 1),
    ("slack-token", "high", re.compile(r"\b(xox[baprs]-[A-Za-z0-9-]{10,})\b"), 1),
    ("google-api-key", "high", re.compile(r"\b(AIza[0-9A-Za-z_\-]{35})\b"), 1),
    ("stripe-secret", "high", re.compile(r"\b(sk_live_[0-9A-Za-z]{16,})\b"), 1),
    ("slack-webhook", "high",
     re.compile(r"(https://hooks\.slack\.com/services/[A-Za-z0-9/]+)"), 1),
    # Generic assignment: KEY = "value" where the name smells secret and the
    # value is long enough to be one. Value captured for redaction.
    ("generic-secret", "high", re.compile(
        r"(?i)\b(?:api[_-]?key|secret|token|password|passwd|access[_-]?token|"
        r"client[_-]?secret|private[_-]?key)\b\s*[:=]\s*['\"]([^'\"]{12,})['\"]"), 1),
]


def _redact_line(text):
    """Return (redacted_text, [(label, severity, value)]) for one line."""
    hits = []
    redacted = text
    for label, severity, rx, gi in _RULES:
        for m in rx.finditer(text):
            value = m.group(gi) if gi and gi <= (m.lastindex or 0) else m.group(0)
            hits.append((label, severity, value))
            if value:
                redacted = redacted.replace(value, f"***REDACTED-{label}***")
    return redacted, hits


def scan(ctx):
    findings = []
    redactions = {}  # secret value -> placeholder (applied to whole diff later)
    for path, lineno, text in iter_added_lines(ctx.diff_text):
        _, hits = _redact_line(text)
        for label, severity, value in hits:
            findings.append(finding(
                NAME, severity,
                f"possible {label} committed in diff", path=path, line=lineno))
            if value:
                redactions[value] = f"***REDACTED-{label}***"

    # Build the redacted diff by replacing every detected secret value.
    redacted_text = ctx.diff_text
    # Replace longer secrets first to avoid partial-overlap artifacts.
    for value in sorted(redactions, key=len, reverse=True):
        redacted_text = redacted_text.replace(value, redactions[value])
    ctx.redacted_diff_text = redacted_text
    ctx.secrets_redacted = len(redactions)
    return findings
