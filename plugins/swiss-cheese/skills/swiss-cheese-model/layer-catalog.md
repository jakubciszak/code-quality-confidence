# Layer catalog

Predefined Swiss Cheese layers. Each entry: what it catches, how it's configured, and its **known holes** (what it will miss — the reason it needs neighbors).

## instructions — `knowledge`
Guardrails in CLAUDE.md / agent instructions: conventions, forbidden patterns, the defense stack itself.
Config: `{"id": "instructions", "type": "knowledge", "notes": "CLAUDE.md §Swiss Cheese layers"}`
Holes: agents drift from instructions under long context; instructions rot as the project evolves. Cheapest layer, weakest enforcement.

## lint — `scripted`
Linting & static analysis (ruff, eslint, golangci-lint, clippy…). Structural and stylistic defects, some bug classes.
Config: `{"id": "lint", "type": "scripted", "command": "ruff check .", "fast": true}`
Holes: blind to logic, design and anything without a rule; suppressions accumulate.

## typecheck — `scripted`
mypy/pyright/tsc/compiler. Interface and nullability defects.
Config: `{"id": "typecheck", "type": "scripted", "command": "npx tsc --noEmit", "fast": true}`
Holes: `Any`/casts punch holes on demand; runtime behavior invisible.

## tests — `scripted`
The project's test suite. The only layer that checks *behavior*.
Config: `{"id": "tests", "type": "scripted", "command": "pytest -q", "fast": false, "timeout": 1800}`
Holes: only as good as coverage; passes trivially for untested code; agents can "fix" a failure by weakening the test (the review layer's tests slice watches for exactly this).

## agent-hooks — `hook`
Per-edit checks fed back to the agent seconds after each Write/Edit (plugin's PostToolUse hook, `scripts/hook_gate.py`). The fastest feedback slice.
Config: `{"id": "agent-hooks", "type": "hook", "on_edit": {".py": "ruff check --quiet {file}", ".ts": "npx eslint {file}"}}`
Holes: per-file only — cross-file breakage invisible; skipped when tools other than Write/Edit change files (git checkout, scripts).

## pre-commit — `scripted` (installed as git hook)
Same checks as lint/typecheck but enforced before a commit exists. Catches what slipped past hooks in non-agent edits.
Config: `{"id": "pre-commit", "type": "scripted", "command": "pre-commit run --all-files", "fast": true}` plus `.pre-commit-config.yaml` (template in plugin).
Holes: `--no-verify` bypasses it; local-machine only.

## secrets-scan — `scripted`
Secrets and dependency vulnerability scanning (gitleaks, trufflehog, pip-audit, npm audit, osv-scanner).
Config: `{"id": "secrets-scan", "type": "scripted", "command": "gitleaks protect --staged --no-banner", "fast": true}`
Holes: entropy heuristics miss structured secrets; advisories lag zero-days.

## review — `agents` (composite slice)
Multi-agent code review: correctness, security, architecture, performance, tests, docs — each an independent sub-slice with its own lens. `scripts/diff_snapshot.py` generates ONE shared diff and selects which sub-agents this change actually warrants (`selection: "auto"`).
Config: `{"id": "review", "type": "agents", "selection": "auto", "agents": ["correctness","security","architecture","performance","tests","docs"], "style": "severity-gated"}`
Holes: LLM slices hallucinate and miss novel patterns; auto-selection heuristics can skip a relevant lens (use `--all` for critical changes).

## ci — `scripted` (remote)
The CI pipeline: whole-codebase, clean-environment, deterministic. The backstop for everything environment-dependent.
Config: `{"id": "ci", "type": "process", "notes": ".github/workflows/ci.yml", "enabled": true}` — CI runs remotely; locally it's represented by keeping scripted layers identical to CI steps.
Holes: slow feedback; anything not in the pipeline; flaky tests train people to ignore red.

## docs — `knowledge`
Documentation & ADR discipline: README, CONTRIBUTING, ARCHITECTURE, `docs/adr/`. Catches the class of defect caused by *missing context* — the holes humans and agents fall through months later.
Config: `{"id": "docs", "type": "knowledge", "adr_dir": "docs/adr"}`
Holes: docs rot silently (the review layer's docs slice patrols drift); writing them feels optional under deadline.

## human-review — `process`
A human with context, aided by machine findings, judging what automation can't: intent, product fit, architectural taste.
Config: `{"id": "human-review", "type": "process", "checklist": "docs/review-checklist.md"}`
Holes: fatigue, rubber-stamping, experience blind spots. Machine layers exist to spend scarce human attention only where judgment matters.

## dynamic-testing — `scripted` (high-risk profiles)
DAST, fuzzing, chaos/fault injection (OWASP ZAP, Toxiproxy, race detectors). Tests the *running* system where static layers are blind.
Config: `{"id": "dynamic-testing", "type": "scripted", "command": "<project-specific>", "fast": false}`
Holes: business-logic flaws pass; environment fidelity limits findings; expensive — justify with the risk profile.

## Custom layers

Anything with a named failure mode the catalog doesn't cover: license compliance, i18n completeness, accessibility, migration-safety, feature-flag hygiene, PII lineage… Build via `/swiss-cheese:layer custom` (the `custom-layer` skill holds the methodology). Type `custom` entries must declare `"holes"`.
