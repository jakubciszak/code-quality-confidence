"""Swiss Cheese guards — deterministic, stdlib-only pre-LLM defense layer.

Each guard is a self-contained module exposing `NAME` and
`scan(ctx) -> list[finding]`, so it can run from a hook with no model in the
loop. Findings are plain dicts: {guard, severity, path?, line?, match?, message}.

This package module holds the shared machinery: the unified-diff parser, a
`**`-aware glob matcher, and reference-file loading with embedded fallbacks
(a guard must keep working even if its reference file is missing).
"""

import json
import os
import re

# Locate references/ relative to this package: scripts/guards/ -> plugin root.
_PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REFS_DIR = os.path.join(_PLUGIN_ROOT, "references")


def load_ref_json(name, fallback):
    """Load references/<name>, returning `fallback` if missing/unreadable.

    Guards embed a minimal fallback so they never go silent just because a
    data file was moved. The reference file, when present, is authoritative.
    """
    path = os.path.join(REFS_DIR, name)
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return fallback


def finding(guard, severity, message, path=None, line=None, match=None):
    out = {"guard": guard, "severity": severity, "message": message}
    if path is not None:
        out["path"] = path
    if line is not None:
        out["line"] = line
    if match is not None:
        out["match"] = match[:120]
    return out


_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def iter_added_lines(diff_text):
    """Yield (path, new_line_number, text) for every added ('+') diff line.

    Skips file headers (`+++`). `path` is the post-image path (`b/...`).
    Line numbers track the new file per hunk header. Pure parsing — the diff
    is treated strictly as data.
    """
    path = None
    new_lineno = 0
    for line in diff_text.splitlines():
        if line.startswith("+++ "):
            raw = line[4:].strip()
            if raw == "/dev/null":
                path = None
            else:
                path = raw[2:] if raw.startswith("b/") else raw
            continue
        if line.startswith("--- "):
            continue
        if line.startswith("diff --git"):
            path = None
            continue
        m = _HUNK_RE.match(line)
        if m:
            new_lineno = int(m.group(1))
            continue
        if line.startswith("+"):
            yield path, new_lineno, line[1:]
            new_lineno += 1
        elif line.startswith("-"):
            continue  # removed line: new file line number does not advance
        else:
            new_lineno += 1  # context line advances the new-file counter


def _glob_to_regex(glob):
    """Translate a path glob (supporting **, *, ?) to an anchored regex."""
    i, n, out = 0, len(glob), []
    while i < n:
        c = glob[i]
        if c == "*":
            if i + 1 < n and glob[i + 1] == "*":
                # ** matches across path separators
                out.append(".*")
                i += 2
                if i < n and glob[i] == "/":
                    i += 1
                continue
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(c))
        i += 1
    return re.compile("^" + "".join(out) + "$")


def path_matches(path, globs):
    """True if `path` (or its basename) matches any glob in `globs`."""
    if not path:
        return False
    base = os.path.basename(path)
    for g in globs:
        rx = _glob_to_regex(g)
        if rx.match(path) or rx.match(base):
            return True
    return False


def all_added_text(diff_text):
    """Concatenated added-line text (for cheap whole-diff substring checks)."""
    return "\n".join(text for _, _, text in iter_added_lines(diff_text))
