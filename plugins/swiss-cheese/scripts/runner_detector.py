#!/usr/bin/env python3
"""runner_detector.py — detect HOW to run a tool in this repository.

`/swiss-cheese:init` and `/swiss-cheese:layer add` use this instead of
guessing a command and probing `--version`. For each logical task (test,
lint, typecheck, format, build) it resolves the best command by inspecting,
in priority order:

    Makefile -> package.json -> composer.json -> pyproject.toml
    (tox/hatch/poetry) -> justfile -> Taskfile.yml -> docker-compose.yml
    -> direct binaries (node_modules/.bin, vendor/bin, .venv/bin, PATH)

Writes .swiss-cheese/runners.json; each entry carries: command, via,
rationale, confidence, alternatives[]. It also proposes high_risk_paths from
a directory probe (auth/payments/migrations/...) for init to confirm, rather
than leaving the list empty.

Stdlib only. tomllib is used when present (py3.11+), else a regex fallback.
"""

import argparse
import json
import os
import re
import shutil
import sys

try:
    import tomllib
except Exception:  # pragma: no cover - py<3.11
    tomllib = None

TASKS = {
    "test": {"synonyms": ["test", "tests", "check", "pytest", "unittest", "spec"],
             "binaries": ["pytest", "jest", "vitest", "go", "cargo", "phpunit", "rspec"]},
    "lint": {"synonyms": ["lint", "ruff", "eslint", "flake8", "rubocop", "check"],
             "binaries": ["ruff", "eslint", "flake8", "golangci-lint", "clippy",
                          "rubocop", "phpstan"]},
    "typecheck": {"synonyms": ["typecheck", "types", "mypy", "tsc", "pyright"],
                  "binaries": ["mypy", "tsc", "pyright"]},
    "format": {"synonyms": ["format", "fmt", "prettier", "black", "gofmt"],
               "binaries": ["black", "prettier", "gofmt", "rustfmt"]},
    "build": {"synonyms": ["build", "compile", "dist", "bundle"],
              "binaries": ["tsc", "webpack", "vite", "go", "cargo"]},
}

HIGH_RISK_DIRNAMES = {
    "auth", "authentication", "authorization", "authz", "login", "identity",
    "payment", "payments", "billing", "checkout", "invoice", "invoicing",
    "migration", "migrations", "security", "crypto", "credentials", "secrets",
    "permissions", "rbac", "iam",
}
SKIP_DIRS = {".git", "node_modules", "vendor", "dist", "build", "target",
             ".venv", "venv", "__pycache__", ".swiss-cheese", ".tox", "out"}


# --- source detectors (each returns {name: raw_target}) --------------------

def detect_make_targets(root):
    path = os.path.join(root, "Makefile")
    if not os.path.exists(path):
        return {}
    targets = {}
    for line in _read(path).splitlines():
        m = re.match(r"^([A-Za-z0-9_][A-Za-z0-9_-]*):(?!=)", line)
        if m:
            targets[m.group(1)] = m.group(1)
    return targets


def detect_package_scripts(root):
    return _json_scripts(os.path.join(root, "package.json"))


def detect_composer_scripts(root):
    return _json_scripts(os.path.join(root, "composer.json"))


def detect_just_recipes(root):
    for name in ("justfile", "Justfile", ".justfile"):
        path = os.path.join(root, name)
        if os.path.exists(path):
            return {m.group(1): m.group(1)
                    for line in _read(path).splitlines()
                    if (m := re.match(r"^([A-Za-z0-9_][A-Za-z0-9_-]*):", line))}
    return {}


def detect_taskfile_tasks(root):
    for name in ("Taskfile.yml", "Taskfile.yaml"):
        path = os.path.join(root, name)
        if os.path.exists(path):
            tasks, in_tasks = {}, False
            for line in _read(path).splitlines():
                if re.match(r"^tasks:\s*$", line):
                    in_tasks = True
                    continue
                if in_tasks:
                    if re.match(r"^\S", line):  # dedent out of tasks:
                        break
                    m = re.match(r"^  ([A-Za-z0-9_][A-Za-z0-9_-]*):", line)
                    if m:
                        tasks[m.group(1)] = m.group(1)
            return tasks
    return {}


def detect_pyproject(root):
    """Return (backend, scripts) where backend is poetry|tox|hatch|None."""
    path = os.path.join(root, "pyproject.toml")
    tox_ini = os.path.join(root, "tox.ini")
    data, text = None, ""
    if os.path.exists(path):
        text = _read(path)
        if tomllib:
            try:
                data = tomllib.loads(text)
            except Exception:
                data = None
    backend = None
    if os.path.exists(tox_ini) or "[tool.tox]" in text:
        backend = "tox"
    elif "[tool.hatch.envs" in text or "[tool.hatch]" in text:
        backend = "hatch"
    elif "[tool.poetry]" in text:
        backend = "poetry"
    scripts = {}
    if data:
        scripts.update((data.get("tool", {}).get("poetry", {}) or {}).get("scripts", {}))
    return backend, scripts


def detect_compose_services(root):
    for name in ("docker-compose.yml", "docker-compose.yaml", "compose.yml"):
        path = os.path.join(root, name)
        if os.path.exists(path):
            services, in_services = [], False
            for line in _read(path).splitlines():
                if re.match(r"^services:\s*$", line):
                    in_services = True
                    continue
                if in_services:
                    if re.match(r"^\S", line):
                        break
                    m = re.match(r"^  ([A-Za-z0-9_.-]+):", line)
                    if m:
                        services.append(m.group(1))
            return services
    return []


def detect_local_binary(root, name):
    """Locate a binary vendored inside the repo, or None."""
    for rel in (os.path.join("node_modules", ".bin", name),
                os.path.join("vendor", "bin", name),
                os.path.join(".venv", "bin", name)):
        cand = os.path.join(root, rel)
        if os.path.exists(cand):
            return rel.replace(os.sep, "/")
    return None


def detect_binary(root, name):
    """Locate a binary in local vendor dirs first, then PATH."""
    return detect_local_binary(root, name) or (name if shutil.which(name) else None)


# --- resolution ------------------------------------------------------------

def _match_synonym(names, synonyms):
    """Return the first key whose lowercased name matches a synonym."""
    lowered = {k.lower(): k for k in names}
    for syn in synonyms:
        if syn in lowered:
            return lowered[syn]
    # partial: a name that starts with / contains a synonym token
    for key in names:
        kl = key.lower()
        if any(kl == syn or kl.startswith(syn + ":") or kl.startswith(syn + "-")
               for syn in synonyms):
            return key
    return None


def resolve(root, task, include_path=True):
    """Resolve the best command for `task`.

    include_path=False restricts detection to what lives *in the repo*
    (manifests + vendored binaries), ignoring globally-installed tools on
    PATH — used to reason about a repo independent of the host toolbox.
    """
    spec = TASKS[task]
    syns = spec["synonyms"]
    candidates = []  # (command, via, rationale, confidence)

    make = detect_make_targets(root)
    if (t := _match_synonym(make, syns)):
        candidates.append((f"make {t}", "Makefile", f"Makefile target '{t}'", "high"))

    pkg = detect_package_scripts(root)
    if (t := _match_synonym(pkg, syns)):
        candidates.append((f"npm run {t}", "package.json", f"npm script '{t}'", "high"))

    comp = detect_composer_scripts(root)
    if (t := _match_synonym(comp, syns)):
        candidates.append((f"composer {t}", "composer.json", f"composer script '{t}'", "high"))

    backend, scripts = detect_pyproject(root)
    if (t := _match_synonym(scripts, syns)):
        candidates.append((f"poetry run {t}", "pyproject.toml", f"poetry script '{t}'", "high"))
    elif backend == "tox" and task in ("test", "lint", "typecheck"):
        candidates.append(("tox", "pyproject.toml", "tox environment runner", "medium"))
    elif backend == "hatch" and (t := _match_synonym({task: task}, syns)):
        candidates.append((f"hatch run {task}", "pyproject.toml", f"hatch env '{task}'", "medium"))

    just = detect_just_recipes(root)
    if (t := _match_synonym(just, syns)):
        candidates.append((f"just {t}", "justfile", f"just recipe '{t}'", "high"))

    taskf = detect_taskfile_tasks(root)
    if (t := _match_synonym(taskf, syns)):
        candidates.append((f"task {t}", "Taskfile.yml", f"Taskfile task '{t}'", "high"))

    # Prefer a binary vendored in the repo over any global PATH tool,
    # regardless of list order. Fall back to PATH only if no local one exists.
    local_hit = path_hit = None
    for binary in spec["binaries"]:
        loc = detect_local_binary(root, binary)
        if loc and local_hit is None:
            local_hit = (loc, binary, "high")
        elif include_path and path_hit is None and shutil.which(binary):
            path_hit = (binary, binary, "medium")
    chosen = local_hit or path_hit
    if chosen:
        loc, binary, conf = chosen
        candidates.append((loc, "binary", f"{binary} available ({loc})", conf))

    services = detect_compose_services(root)
    if services and not candidates:
        candidates.append((f"docker compose run {services[0]} {task}",
                           "docker-compose.yml",
                           f"fallback via compose service '{services[0]}'", "low"))

    if not candidates:
        return None
    primary = candidates[0]
    return {
        "command": primary[0],
        "via": primary[1],
        "rationale": primary[2],
        "confidence": primary[3],
        "alternatives": [{"command": c[0], "via": c[1]} for c in candidates[1:]],
    }


def propose_high_risk_paths(root):
    found = set()
    for dirpath, dirnames, _ in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for d in list(dirnames):
            if d.lower() in HIGH_RISK_DIRNAMES:
                rel = os.path.relpath(os.path.join(dirpath, d), root).replace(os.sep, "/")
                found.add(f"{rel}/**")
    return sorted(found)


# --- io helpers ------------------------------------------------------------

def _read(path):
    try:
        return open(path, encoding="utf-8", errors="ignore").read()
    except OSError:
        return ""


def _json_scripts(path):
    if not os.path.exists(path):
        return {}
    try:
        return json.load(open(path, encoding="utf-8")).get("scripts", {}) or {}
    except Exception:
        return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default=".")
    ap.add_argument("--task", help="resolve a single task instead of all")
    ap.add_argument("--out", default=".swiss-cheese/runners.json")
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args()

    root = os.path.abspath(args.path)
    tasks = [args.task] if args.task else list(TASKS)
    runners = {}
    for task in tasks:
        if task not in TASKS:
            continue
        r = resolve(root, task)
        if r:
            runners[task] = r

    result = {"runners": runners,
              "high_risk_paths": propose_high_risk_paths(root)}

    if not args.no_write:
        out = args.out if os.path.isabs(args.out) else os.path.join(root, args.out)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=1)
    json.dump(result, sys.stdout, separators=(",", ":"))
    print()


if __name__ == "__main__":
    main()
