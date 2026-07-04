#!/usr/bin/env python3
"""diff_snapshot.py — generate ONE canonical diff for the whole review layer.

The multi-agent review layer must never re-run `git diff` per agent. This
script produces the diff exactly once, classifies every changed file, and
decides deterministically which review agents are worth spawning for this
particular change. Agents then Read the same diff.patch from disk.

Usage:
    python3 diff_snapshot.py [--base <ref>] [--staged] [--all] [--out <dir>]

  --base <ref>   diff against a ref (default: merge-base with default branch;
                 falls back to HEAD, i.e. uncommitted changes)
  --staged       diff only staged changes
  --all          recommend every review agent regardless of heuristics
  --out <dir>    output dir (default: .swiss-cheese/runs/latest)

Writes:
    <out>/diff.patch      the single shared diff
    <out>/manifest.json   per-file stats, categories, agent selection + reasons

Prints the manifest (compact JSON) to stdout so the orchestrator sees the
selection without extra Read calls. Stdlib only.
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
DEPS_FILE = re.compile(
    r"(^|/)(requirements[^/]*\.txt|pyproject\.toml|Pipfile|package\.json|"
    r"package-lock\.json|yarn\.lock|pnpm-lock\.yaml|go\.(mod|sum)|Cargo\.(toml|lock)|"
    r"pom\.xml|build\.gradle(\.kts)?|Gemfile(\.lock)?|composer\.(json|lock)|mix\.exs)$")
TEST_FILE = re.compile(
    r"(^|/)(tests?|spec|__tests__|e2e)(/|$)|(_test\.(py|go)|\.test\.[jt]sx?|"
    r"\.spec\.[jt]sx?|Test\.java|_spec\.rb)")
DOC_FILE = re.compile(r"\.(md|rst|adoc|txt)$|(^|/)docs?(/|$)", re.I)
DB_FILE = re.compile(r"migrat|schema|\.sql$|(^|/)models?(/|$)|(^|/)entit(y|ies)(/|$)", re.I)
CI_FILE = re.compile(r"(^|/)\.github/workflows/|\.gitlab-ci|(^|/)\.circleci/|Jenkinsfile|Dockerfile|docker-compose", re.I)
CONFIG_FILE = re.compile(r"\.(ya?ml|toml|ini|cfg|conf|env[^/]*|properties)$|(^|/)config(/|$)", re.I)
CODE_EXT = re.compile(r"\.(py|ts|tsx|js|jsx|go|rs|java|kt|rb|php|cs|cpp|cc|c|h|swift|scala|ex|exs|sh|dart)$")

RISKY_ADDED = re.compile(
    r"\b(eval|exec)\s*\(|subprocess|os\.system|shell\s*=\s*True|dangerouslySetInnerHTML|"
    r"innerHTML\s*=|SELECT\s+.+\s+FROM|INSERT\s+INTO|DELETE\s+FROM|DROP\s+TABLE|"
    r"pickle\.loads|yaml\.load\(|md5|sha1\b|verify\s*=\s*False|http://|"
    r"password|secret|api[-_]?key|BEGIN (RSA|OPENSSH) PRIVATE KEY|AKIA[0-9A-Z]{16}", re.I)
PERF_HINT = re.compile(
    r"(^|/)(worker|queue|batch|stream|parser|cache|index|search|pipeline|cron|job)s?(/|\.|_)", re.I)
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
    return "HEAD"  # uncommitted changes only


def classify(path):
    cats = set()
    if TEST_FILE.search(path):
        cats.add("tests")
    if DOC_FILE.search(path):
        cats.add("docs")
    if DEPS_FILE.search(path):
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


def select_agents(files, flags, force_all):
    all_agents = ["correctness", "security", "architecture", "performance", "tests", "docs"]
    if force_all:
        return {a: "forced via --all" for a in all_agents}, {}

    cats = set().union(*(f["categories"] for f in files)) if files else set()
    code_files = [f for f in files if "code" in f["categories"] or "db" in f["categories"]]
    new_files = [f for f in files if f["status"] == "A" and "code" in f["categories"]]
    added_total = sum(f["added"] for f in files)

    picked, skipped = {}, {}

    def pick(agent, reason):
        picked[agent] = reason

    if code_files or "db" in cats or "config" in cats:
        pick("correctness", f"{len(code_files)} code/db file(s) changed")
    else:
        skipped["correctness"] = "no code changes (docs/tests only)"

    sec_reasons = []
    if "security" in cats:
        sec_reasons.append("security-sensitive paths touched")
    if "deps" in cats:
        sec_reasons.append("dependency manifest changed")
    if flags["risky_lines"]:
        sec_reasons.append(f"risky patterns in added lines: {', '.join(sorted(flags['risky_lines'])[:5])}")
    if "ci" in cats:
        sec_reasons.append("CI/Docker files changed")
    if sec_reasons:
        pick("security", "; ".join(sec_reasons))
    else:
        skipped["security"] = "no security-sensitive paths, deps, CI or risky patterns"

    arch_reasons = []
    if len(new_files) >= 2:
        arch_reasons.append(f"{len(new_files)} new source files")
    if len(files) >= 8:
        arch_reasons.append(f"{len(files)} files touched")
    if "deps" in cats:
        arch_reasons.append("dependencies changed")
    if flags["api_surface"]:
        arch_reasons.append("public API surface changed")
    if arch_reasons:
        pick("architecture", "; ".join(arch_reasons))
    else:
        skipped["architecture"] = "small, local change"

    perf_reasons = []
    if "db" in cats:
        perf_reasons.append("DB/schema/query changes")
    if any(PERF_HINT.search(f["path"]) for f in files):
        perf_reasons.append("hot-path modules touched (worker/queue/cache/...)")
    if added_total > 300 and code_files:
        perf_reasons.append(f"large change (+{added_total} lines)")
    if perf_reasons:
        pick("performance", "; ".join(perf_reasons))
    else:
        skipped["performance"] = "no DB, hot paths or large code additions"

    tests_changed = "tests" in cats
    if code_files and not tests_changed:
        pick("tests", "code changed with NO test changes — coverage gap likely")
    elif tests_changed:
        pick("tests", "tests changed — verify they assert real behavior")
    else:
        skipped["tests"] = "no code or test changes"

    if "docs" in cats:
        pick("docs", "documentation changed")
    elif flags["api_surface"] and code_files:
        pick("docs", "public API changed but no docs touched")
    else:
        skipped["docs"] = "no docs impact detected"

    return picked, skipped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base")
    ap.add_argument("--staged", action="store_true")
    ap.add_argument("--all", action="store_true")
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
        # nothing unstaged — try staged as a fallback
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

    files = []
    for line in git(stat_args).splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        added, deleted, path = parts
        files.append({
            "path": path,
            "added": int(added) if added.isdigit() else 0,
            "deleted": int(deleted) if deleted.isdigit() else 0,
            "status": status.get(path, "M"),
            "categories": sorted(classify(path)),
        })
    for f in files:
        f["categories"] = set(f["categories"])

    risky, api_surface = set(), False
    for line in diff.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            m = RISKY_ADDED.search(line)
            if m:
                risky.add(m.group(0).strip().lower()[:30])
            if API_SURFACE_ADDED.match(line):
                api_surface = True
    flags = {"risky_lines": risky, "api_surface": api_surface}

    picked, skipped = select_agents(files, flags, args.all)

    os.makedirs(args.out, exist_ok=True)
    diff_path = os.path.join(args.out, "diff.patch")
    with open(diff_path, "w", encoding="utf-8") as fh:
        fh.write(diff)

    for f in files:
        f["categories"] = sorted(f["categories"])
    manifest = {
        "base": base or "staged",
        "diff_path": os.path.abspath(diff_path),
        "totals": {"files": len(files),
                   "added": sum(f["added"] for f in files),
                   "deleted": sum(f["deleted"] for f in files)},
        "files": files,
        "flags": {"risky_lines": sorted(risky), "api_surface_changed": api_surface},
        "recommended_reviews": [{"agent": a, "reason": r} for a, r in picked.items()],
        "skipped_reviews": [{"agent": a, "reason": r} for a, r in skipped.items()],
    }
    with open(os.path.join(args.out, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1)
    json.dump(manifest, sys.stdout, separators=(",", ":"))
    print()


if __name__ == "__main__":
    main()
