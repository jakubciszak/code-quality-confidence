# Layer catalog

Predefined Swiss Cheese layers. Each entry: what it catches, how it's configured (schema **v2** — a layer is `"<id>": { "mode": "auto|comment|skip", ... }` inside the `layers` object), and its **named holes** (what it will miss — the reason it needs neighbors). Unnamed holes are the ones that align silently.

`mode` semantics: `auto` gates (a failure/blocker counts against `ok` / can exit 2); `comment` reports but never gates; `skip` is off. Missing external tool ⇒ the layer is `skipped`, never a silent pass.

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

## guards — `guards` (deterministic pre-LLM layer)
Stdlib-only scripts that scan the diff **as data, never executing it**, before any model is spent: `injection` (prompt-injection tokens, comment-and-control phrasings, agent-control-file edits), `secrets` (detect + redact — review lenses only ever see `diff.redacted.patch`), `policy` (LOC thresholds, high-risk-path-without-`human-reviewed`, missing `AI-disclosure`), `slopsquat` (typosquatted/hallucinated deps), `high_risk` (paths that force escalation). Runs from a `PreToolUse` commit hook (`scripts/guard_hook.py`) so a `blocker` is a hard `exit 2` with zero token cost.
Config: `"guards": {"mode": "auto"}` (per-guard override: `"guards": {"injection": "auto", "slopsquat": "comment"}` at the config root).
Holes: **regex-based** — a new phrasing of "ignore your instructions" that dodges the literal patterns slips through; **slopsquat is blind to packages that are legitimate but compromised** (a real, popular package that was backdoored looks fine to edit-distance and registry checks); binary/minified blobs aren't scanned line-by-line.

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
Multi-lens code review: core, security, architecture, performance, tests, docs, and `staff` (the highest lens) — each an independent read-only subagent with its own lens, spawned **explicitly** by the `review` skill (one always-on description instead of seven auto-invoked agents). `scripts/select_agents.py` computes a deterministic **`required`** lens floor from `manifest.json` + `guards.json`; the model may only *add* lenses, never remove one. High-risk paths escalate `architecture`/`staff` to Opus.
Config: `"review": {"mode": "auto"}`
Holes: LLM slices hallucinate and miss novel patterns; the model can raise vigilance but the deterministic floor is what guarantees coverage — a lens the rules don't require and the model doesn't add won't run.

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
