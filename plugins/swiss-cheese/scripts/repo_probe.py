#!/usr/bin/env python3
"""repo_probe.py — deterministic, token-frugal repository scan.

Emits one compact JSON document describing the repository so the agent
does not have to burn tokens exploring the tree with dozens of tool calls.

Usage:
    python3 repo_probe.py [path]

Output (stdout): JSON with languages, build/deps manifests, tests, CI,
linters, type checkers, docs, ADRs, hooks, Claude config, and detected
Swiss Cheese state. Stdlib only — no third-party dependencies.
"""

import glob
import json
import os
import re
import subprocess
import sys

IGNORE_DIRS = {
    ".git", "node_modules", "vendor", "dist", "build", "target", ".venv",
    "venv", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache",
    ".idea", ".vscode", "coverage", ".next", ".nuxt", ".terraform",
    ".swiss-cheese", ".tox", "eggs", ".eggs", "out", "bin", "obj",
}

LANG_EXT = {
    ".py": "python", ".ts": "typescript", ".tsx": "typescript",
    ".js": "javascript", ".jsx": "javascript", ".go": "go", ".rs": "rust",
    ".java": "java", ".kt": "kotlin", ".rb": "ruby", ".php": "php",
    ".cs": "csharp", ".cpp": "cpp", ".cc": "cpp", ".c": "c", ".h": "c",
    ".swift": "swift", ".scala": "scala", ".ex": "elixir", ".exs": "elixir",
    ".sh": "shell", ".sql": "sql", ".tf": "terraform", ".dart": "dart",
}

DEP_MANIFESTS = [
    "pyproject.toml", "requirements.txt", "setup.py", "setup.cfg", "Pipfile",
    "package.json", "pnpm-lock.yaml", "yarn.lock", "package-lock.json",
    "go.mod", "Cargo.toml", "pom.xml", "build.gradle", "build.gradle.kts",
    "Gemfile", "composer.json", "mix.exs", "*.csproj",
]

LINTER_CONFIGS = {
    "ruff": ["ruff.toml", ".ruff.toml"],
    "flake8": [".flake8", "tox.ini"],
    "pylint": [".pylintrc", "pylintrc"],
    "eslint": [".eslintrc", ".eslintrc.js", ".eslintrc.json", ".eslintrc.yml",
               "eslint.config.js", "eslint.config.mjs", "eslint.config.ts"],
    "biome": ["biome.json", "biome.jsonc"],
    "prettier": [".prettierrc", ".prettierrc.json", ".prettierrc.js", "prettier.config.js"],
    "golangci-lint": [".golangci.yml", ".golangci.yaml"],
    "clippy": ["clippy.toml"],
    "rubocop": [".rubocop.yml"],
    "phpstan": ["phpstan.neon", "phpstan.neon.dist"],
    "checkstyle": ["checkstyle.xml"],
    "detekt": ["detekt.yml"],
}

TYPECHECK_CONFIGS = {
    "mypy": ["mypy.ini", ".mypy.ini"],
    "pyright": ["pyrightconfig.json"],
    "typescript": ["tsconfig.json"],
}

CI_PATHS = [
    ".github/workflows", ".gitlab-ci.yml", ".circleci/config.yml",
    "azure-pipelines.yml", "Jenkinsfile", ".travis.yml", "bitbucket-pipelines.yml",
    ".buildkite", ".drone.yml", "cloudbuild.yaml",
]

ADR_DIRS = [
    "docs/adr", "docs/adrs", "docs/architecture/decisions", "docs/decisions",
    "adr", "adrs", "doc/adr", "architecture/decisions",
]

DOC_FILES = [
    "README.md", "CONTRIBUTING.md", "ARCHITECTURE.md", "SECURITY.md",
    "CODE_OF_CONDUCT.md", "CHANGELOG.md", "docs",
]

TEST_HINTS = re.compile(r"(^|/)(tests?|spec|__tests__|e2e|integration[-_]?tests?)(/|$)|"
                        r"(_test\.(py|go)|\.test\.[jt]sx?|\.spec\.[jt]sx?|Test\.java|_spec\.rb)$")


def sh(cmd, cwd):
    try:
        out = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=15)
        return out.stdout.strip() if out.returncode == 0 else None
    except Exception:
        return None


def exists_any(root, paths):
    hits = []
    for p in paths:
        if any(ch in p for ch in "*?["):
            if glob.glob(os.path.join(root, p)):
                hits.append(p)
        elif os.path.exists(os.path.join(root, p)):
            hits.append(p)
    return hits


def main():
    root = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else ".")
    lang_count, test_files, total_files, sample_dirs = {}, 0, 0, set()

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS and not d.startswith(".")
                       or d in (".github", ".claude", ".claude-plugin")]
        rel = os.path.relpath(dirpath, root)
        depth = 0 if rel == "." else rel.count(os.sep) + 1
        if depth <= 2 and rel != ".":
            sample_dirs.add(rel)
        for f in filenames:
            total_files += 1
            ext = os.path.splitext(f)[1].lower()
            lang = LANG_EXT.get(ext)
            relf = os.path.join(rel, f) if rel != "." else f
            if lang:
                lang_count[lang] = lang_count.get(lang, 0) + 1
            if TEST_HINTS.search(relf.replace(os.sep, "/")):
                test_files += 1

    languages = sorted(lang_count.items(), key=lambda kv: -kv[1])

    linters = {name: hits for name, cfgs in LINTER_CONFIGS.items()
               if (hits := exists_any(root, cfgs))}
    typecheckers = {name: hits for name, cfgs in TYPECHECK_CONFIGS.items()
                    if (hits := exists_any(root, cfgs))}

    # linters/typecheckers declared inside pyproject.toml / package.json
    for mf, keys in (("pyproject.toml", ["ruff", "mypy", "pytest", "black"]),
                     ("package.json", ["eslint", "prettier", "jest", "vitest", "typescript", "husky", "lint-staged"])):
        p = os.path.join(root, mf)
        if os.path.exists(p):
            try:
                body = open(p, encoding="utf-8", errors="ignore").read()
                for k in keys:
                    if k in body:
                        linters.setdefault(k, []).append(mf)
            except OSError:
                pass

    adr_dirs = []
    for d in ADR_DIRS:
        full = os.path.join(root, d)
        if os.path.isdir(full):
            adr_dirs.append({"dir": d, "count": len([f for f in os.listdir(full) if f.endswith(".md")])})

    claude_dir = os.path.join(root, ".claude")
    claude = {
        "claude_md": os.path.exists(os.path.join(root, "CLAUDE.md")),
        "agents": sorted(os.listdir(os.path.join(claude_dir, "agents")))
        if os.path.isdir(os.path.join(claude_dir, "agents")) else [],
        "skills": sorted(os.listdir(os.path.join(claude_dir, "skills")))
        if os.path.isdir(os.path.join(claude_dir, "skills")) else [],
        "settings": os.path.exists(os.path.join(claude_dir, "settings.json")),
        "hooks_configured": False,
    }
    settings_path = os.path.join(claude_dir, "settings.json")
    if os.path.exists(settings_path):
        try:
            claude["hooks_configured"] = "hooks" in json.load(open(settings_path, encoding="utf-8"))
        except Exception:
            pass

    sc_config = os.path.join(root, ".swiss-cheese", "config.json")
    swiss_cheese = None
    if os.path.exists(sc_config):
        try:
            cfg = json.load(open(sc_config, encoding="utf-8"))
            raw_layers = cfg.get("layers", [])
            if isinstance(raw_layers, dict):  # v2: id -> layer
                layers = [{"id": lid, "type": layer.get("type"),
                           "mode": layer.get("mode", "auto")}
                          for lid, layer in raw_layers.items()]
            else:  # v1: list of layer dicts
                layers = [{"id": layer.get("id"), "type": layer.get("type"),
                           "enabled": layer.get("enabled", True)}
                          for layer in raw_layers]
            swiss_cheese = {"initialized": True, "version": cfg.get("version", 1),
                            "layers": layers}
        except Exception:
            swiss_cheese = {"initialized": True, "layers": "unreadable"}

    default_branch = sh(["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"], root)
    result = {
        "root": root,
        "total_files": total_files,
        "languages": [{"lang": lang, "files": count} for lang, count in languages[:6]],
        "top_dirs": sorted(sample_dirs)[:40],
        "dependency_manifests": exists_any(root, DEP_MANIFESTS),
        "tests": {"test_files": test_files,
                  "has_tests": test_files > 0},
        "ci": exists_any(root, CI_PATHS),
        "linters": linters,
        "typecheckers": typecheckers,
        "precommit": exists_any(root, [".pre-commit-config.yaml", ".husky", "lefthook.yml"]),
        "docs": exists_any(root, DOC_FILES),
        "adr": adr_dirs,
        "codeowners": exists_any(root, ["CODEOWNERS", ".github/CODEOWNERS", "docs/CODEOWNERS"]),
        "pr_template": exists_any(root, [".github/pull_request_template.md",
                                         ".github/PULL_REQUEST_TEMPLATE.md",
                                         "PULL_REQUEST_TEMPLATE.md"]),
        "claude": claude,
        "swiss_cheese": swiss_cheese or {"initialized": False},
        "git": {"default_branch": (default_branch or "").replace("origin/", "") or None,
                "commit_count_90d": sh(["git", "rev-list", "--count", "--since=90.days", "HEAD"], root)},
    }
    json.dump(result, sys.stdout, separators=(",", ":"))
    print()


if __name__ == "__main__":
    main()
