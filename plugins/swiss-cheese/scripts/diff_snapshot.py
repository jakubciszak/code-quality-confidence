#!/usr/bin/env python3
"""diff_snapshot.py — produce ONE canonical diff + manifest for the run.

The review layer must never re-run `git diff` per agent. This script produces
the diff exactly once, classifies each changed file, and records the facts a
downstream deterministic selector (select_agents.py) and the guards need:
per-file LOC and categories, detected dependency manifests (with ecosystem),
and cheap diff-content flags. It does NOT pick review agents — that is
select_agents.py's job (a pure function of manifest.json + guards.json).

Usage:
    python3 diff_snapshot.py [--base <ref>] [--staged] [--out <dir>]

Writes:
    <out>/diff.patch      the single shared raw diff
    <out>/manifest.json   per-file stats, categories, deps, flags

Prints the manifest (compact JSON) to stdout. Stdlib only.
"""

import argparse
import json
import os
import re
import subprocess
import sys

SECURITY_PATH = re.compile(
    r"auth|login|passw|token|secret|crypt|session|permission|acl|oauth|jwt|"
    r"sanitiz|escape|csrf|cors|security|credential|api[-_]?key", re.I)
TEST_FILE = re.compile(
    r"(^|/)(tests?|spec|__tests__|e2e)(/|$)|(_test\.(py|go)|\.test\.[jt]sx?|"
    r"\.spec\.[jt]sx?|Test\.java|_spec\.rb)")
DOC_FILE = re.compile(r"\.(md|rst|adoc|txt)$|(^|/)docs?(/|$)", re.I)
DB_FILE = re.compile(r"migrat|schema|\.sql$|(^|/)models?(/|$)|(^|/)entit(y|ies)(/|$)", re.I)
CI_FILE = re.compile(r"(^|/)\.github/workflows/|\.gitlab-ci|(^|/)\.circleci/|Jenkinsfile|Dockerfile|docker-compose", re.I)
CONFIG_FILE = re.compile(r"\.(ya?ml|toml|ini|cfg|conf|env[^/]*|properties)$|(^|/)config(/|$)", re.I)
CODE_EXT = re.compile(r"\.(py|ts|tsx|js|jsx|go|rs|java|kt|rb|php|cs|cpp|cc|c|h|swift|scala|ex|exs|sh|dart)$")

# path basename -> (ecosystem, category=deps)
DEP_MANIFESTS = {
    "package.json": "npm", "package-lock.json": "npm", "yarn.lock": "npm",
    "pnpm-lock.yaml": "npm",
    "requirements.txt": "pypi", "pyproject.toml": "pypi", "pipfile": "pypi",
    "setup.py": "pypi", "setup.cfg": "pypi",
    "composer.json": "packagist", "composer.lock": "packagist",
    "cargo.toml": "crates", "cargo.lock": "crates",
    "gemfile": "rubygems", "gemfile.lock": "rubygems",
    "go.mod": "go", "go.sum": "go", "pom.xml": "maven",
    "build.gradle": "maven", "build.gradle.kts": "maven",
}

RISKY_ADDED = re.compile(
    r"\b(eval|exec)\s*\(|subprocess|os\.system|shell\s*=\s*True|dangerouslySetInnerHTML|"
    r"innerHTML\s*=|SELECT\s+.+\s+FROM|INSERT\s+INTO|DELETE\s+FROM|DROP\s+TABLE|"
    r"pickle\.loads|yaml\.load\(|md5|sha1\b|verify\s*=\s*False|http://", re.I)
API_SURFACE_ADDED = re.compile(
    r"^\+\s*(def |class |export |public |func |fn |interface |type \w+ (struct|interface)|@app\.|@router\.|@(Get|Post|Put|Delete|Patch)Mapping)")


def git(args, check=True):
    out = subprocess.run(["git"] + args, capture_output=True, text=True)
    if check and out.returncode != 0:
        sys.stderr.write(out.stderr)
        sys.exit(out.returncode)
    return out.stdout


def resolve_base(explicit, staged):
    if staged:
        return None
    if explicit:
        return explicit
    head = git(["symbolic-ref", "--short", "refs/remotes/origin/HEAD"], check=False).strip()
    default = head.replace("origin/", "") if head else "main"
    for candidate in (f"origin/{default}", default, "origin/main", "origin/master"):
        mb = subprocess.run(["git", "merge-base", "HEAD", candidate],
                            capture_output=True, text=True)
        if mb.returncode == 0:
            base = mb.stdout.strip()
            if base != git(["rev-parse", "HEAD"]).strip():
                return base
    return "HEAD"


def ecosystem_for(path):
    return DEP_MANIFESTS.get(os.path.basename(path).lower())


def classify(path):
    cats = set()
    if TEST_FILE.search(path):
        cats.add("tests")
    if DOC_FILE.search(path):
        cats.add("docs")
    if ecosystem_for(path):
        cats.add("deps")
    if DB_FILE.search(path):
        cats.add("db")
    if CI_FILE.search(path):
        cats.add("ci")
    if SECURITY_PATH.search(path):
        cats.add("security")
    if CONFIG_FILE.search(path) and not cats:
        cats.add("config")
    if CODE_EXT.search(path) and "tests" not in cats and "docs" not in cats:
        cats.add("code")
    return cats or {"other"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base")
    ap.add_argument("--staged", action="store_true")
    ap.add_argument("--out", default=".swiss-cheese/runs/latest")
    args = ap.parse_args()

    base = resolve_base(args.base, args.staged)
    diff_args = ["diff", "--no-color", "--find-renames"]
    stat_args = ["diff", "--numstat", "--find-renames", "--diff-filter=ACMRD"]
    name_args = ["diff", "--name-status", "--find-renames"]
    if args.staged:
        for a in (diff_args, stat_args, name_args):
            a.append("--cached")
    elif base:
        for a in (diff_args, stat_args, name_args):
            a.append(base)

    diff = git(diff_args)
    if not diff.strip() and not args.staged and base == "HEAD":
        diff = git(diff_args + ["--cached"])
        if diff.strip():
            stat_args.append("--cached")
            name_args.append("--cached")

    if not diff.strip():
        json.dump({"empty": True, "base": base,
                   "hint": "no changes found; pass --base <ref> or --staged"}, sys.stdout)
        print()
        return

    status = {}
    for line in git(name_args).splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            status[parts[-1]] = parts[0][0]

    files, dep_manifests = [], []
    for line in git(stat_args).splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        added, deleted, path = parts
        cats = classify(path)
        files.append({
            "path": path,
            "added": int(added) if added.isdigit() else 0,
            "deleted": int(deleted) if deleted.isdigit() else 0,
            "status": status.get(path, "M"),
            "categories": sorted(cats),
        })
        eco = ecosystem_for(path)
        if eco:
            dep_manifests.append({"path": path, "ecosystem": eco})

    risky, api_surface = set(), False
    for line in diff.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            m = RISKY_ADDED.search(line)
            if m:
                risky.add(m.group(0).strip().lower()[:30])
            if API_SURFACE_ADDED.match(line):
                api_surface = True

    os.makedirs(args.out, exist_ok=True)
    diff_path = os.path.join(args.out, "diff.patch")
    with open(diff_path, "w", encoding="utf-8") as fh:
        fh.write(diff)

    manifest = {
        "base": base or "staged",
        "diff_path": os.path.abspath(diff_path),
        "redacted_diff_path": None,
        "totals": {"files": len(files),
                   "added": sum(f["added"] for f in files),
                   "deleted": sum(f["deleted"] for f in files)},
        "files": files,
        "dependency_manifests": dep_manifests,
        "flags": {"risky_lines": sorted(risky), "api_surface_changed": api_surface},
    }
    with open(os.path.join(args.out, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1)
    json.dump(manifest, sys.stdout, separators=(",", ":"))
    print()


if __name__ == "__main__":
    main()
