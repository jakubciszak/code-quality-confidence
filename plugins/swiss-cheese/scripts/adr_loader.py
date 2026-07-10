#!/usr/bin/env python3
"""adr_loader.py — rank ADRs by token overlap with the diff, return top-N paths.

Instead of pasting a static ADR cheat-sheet into every review prompt (it rots
the moment a new ADR lands), rank the project's ADRs by how much their text
overlaps with the change and hand the staff lens only the **top-N paths**. The
agent Reads just those. Same progressive-disclosure principle as skills, applied
to project knowledge.

Usage:
    adr_loader.py [--run-dir .swiss-cheese/runs/latest] [--adr-dir docs/adr]
                  [--top 3] [--repo .]

Prints JSON: {"adr_dir": ..., "top": [{"path", "score", "title"}]}. Stdlib only.
"""

import argparse
import json
import os
import re
import sys

ADR_DIRS = [
    "docs/adr", "docs/adrs", "docs/architecture/decisions", "docs/decisions",
    "adr", "adrs", "doc/adr", "architecture/decisions",
]
TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{3,}")
STOP = {
    "this", "that", "with", "from", "have", "will", "when", "then", "else",
    "code", "test", "tests", "file", "files", "return", "import", "class",
    "self", "none", "true", "false", "value", "should", "would", "which",
    "there", "these", "those", "into", "your", "than", "them", "used", "using",
    "adr", "decision", "context", "status", "consequences", "accepted",
}


def tokenize(text):
    return {t.lower() for t in TOKEN_RE.findall(text)
            if t.lower() not in STOP}


def find_adr_dir(repo, explicit):
    if explicit:
        return explicit if os.path.isdir(os.path.join(repo, explicit)) else None
    for d in ADR_DIRS:
        if os.path.isdir(os.path.join(repo, d)):
            return d
    return None


def diff_tokens(run_dir):
    """Tokens from the redacted diff (preferred) plus changed file paths."""
    for name in ("diff.redacted.patch", "diff.patch"):
        p = os.path.join(run_dir, name)
        if os.path.exists(p):
            text = open(p, encoding="utf-8", errors="ignore").read()
            toks = tokenize(text)
            # weight path components too
            manifest = os.path.join(run_dir, "manifest.json")
            if os.path.exists(manifest):
                try:
                    m = json.load(open(manifest, encoding="utf-8"))
                    for f in m.get("files", []):
                        toks |= tokenize(f.get("path", "").replace("/", " "))
                except Exception:
                    pass
            return toks
    return set()


def first_heading(text):
    for line in text.splitlines():
        s = line.strip().lstrip("#").strip()
        if s:
            return s[:80]
    return ""


def rank(repo, adr_dir, dtokens, top):
    full = os.path.join(repo, adr_dir)
    scored = []
    for name in sorted(os.listdir(full)):
        if not name.lower().endswith((".md", ".markdown")):
            continue
        path = os.path.join(adr_dir, name)
        try:
            text = open(os.path.join(full, name), encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        atokens = tokenize(text)
        score = len(dtokens & atokens)
        if score:
            scored.append({"path": path, "score": score, "title": first_heading(text)})
    scored.sort(key=lambda e: (-e["score"], e["path"]))
    return scored[:top]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", default=".swiss-cheese/runs/latest")
    ap.add_argument("--adr-dir")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--top", type=int, default=3)
    args = ap.parse_args()

    try:
        repo = os.path.abspath(args.repo)
        adr_dir = find_adr_dir(repo, args.adr_dir)
        if not adr_dir:
            json.dump({"adr_dir": None, "top": []}, sys.stdout)
            print()
            return
        dtokens = diff_tokens(args.run_dir if os.path.isabs(args.run_dir)
                              else os.path.join(repo, args.run_dir))
        top = rank(repo, adr_dir, dtokens, args.top)
        json.dump({"adr_dir": adr_dir, "top": top}, sys.stdout, separators=(",", ":"))
        print()
    except Exception as exc:
        json.dump({"adr_dir": None, "top": [], "error": str(exc)}, sys.stdout)
        print()


if __name__ == "__main__":
    main()
