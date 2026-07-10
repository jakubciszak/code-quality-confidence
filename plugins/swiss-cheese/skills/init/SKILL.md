---
name: init
description: Analyze this repo and initialize Swiss Cheese defense layers — config v2, runner detection, high-risk paths, CLAUDE.md guardrails, permissions stanza. Invoke to set up the plugin in a project.
disable-model-invocation: true
---

# Initialize the Swiss Cheese stack

*You don't need perfect defenses — you need enough imperfect ones that the holes never align.* Stay token-frugal: the Python probes replace manual exploration.

## 1. Probe the repo and detect runners (two calls, no tree-walking)

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/repo_probe.py" .
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/runner_detector.py" .
```

`repo_probe` gives languages, manifests, linters, CI, ADRs, existing state. `runner_detector` gives, per task (test/lint/typecheck/format/build), the **exact command** (`command`, `via`, `confidence`, `alternatives`) — use these instead of guessing and probing `--version`. It also proposes `high_risk_paths` from a directory probe.

If already initialized, switch to *update mode*: show current layers vs. findings, propose only deltas.

## 2. Interview (one round, ≤4 questions via AskUserQuestion)

1. **Risk profile** — `low | standard | high` (payments/auth/PII ⇒ high). Sets `block_at`/`warn_at`: high ⇒ `block_at: high, warn_at: medium`; standard ⇒ same but more layers in `comment`; low ⇒ `block_at: blocker`.
2. **Which layers** (multiSelect) — pre-selected from the probe (don't offer typecheck for a shell repo).
3. **High-risk paths** — show the `runner_detector` proposals for confirmation/editing; never leave the list empty when auth/payments/migrations dirs exist.
4. **Where task knowledge lives** — Jira/Linear/GitHub/none (wired by `/swiss-cheese:knowledge`).

## 3. Write `.swiss-cheese/config.json` (schema v2)

Use `templates/config.sample.json` as the structural reference. Fill:
- `version: 2`, `block_at`, `warn_at`, `high_risk_paths` (confirmed), `commit_gate: "warn"`.
- `layers` as an **object** keyed by id, each with `mode: auto | comment | skip`. Scripted layers get the `command` straight from `runner_detector` (and `binary` for PATH-detection). Mark slow suites `"fast": false`.
- The `guards` layer (`mode: auto`) and `review` layer (`mode: auto`).

## 4. Supporting artifacts (only what's missing, no further questions)

- **CLAUDE.md governance** — append `templates/claude-md-section.md` (separate-commit rule for `.claude/`, no-commit-without-consent).
- **ADR scaffold** — if no ADR dir, create `docs/adr/0001-record-architecture-decisions.md` from `templates/adr-template.md`.
- **Review checklist** — `docs/review-checklist.md` from the template.
- **Agent memory** — ensure `.claude/agent-memory/` is NOT gitignored (it's shared team knowledge) while `.swiss-cheese/runs/` IS. Optionally seed `arch_module-map.md` from the probe.

## 5. Permissions stanza — propose, never write

Show a `permissions.deny` stanza (e.g. `Read(./.env*)`) for the user to paste into `.claude/settings.json`. **Never modify `.claude/settings.json` yourself.** Likewise, if a hook stanza is needed, show it and ask for merge.

## 6. Report

Summarize the stack (layers × mode), the runners detected, the confirmed high-risk paths, and documentation gaps the probe found (one-line "why it matters" each). Next steps: `/swiss-cheese:intent` before a ticket, `/swiss-cheese:review` after changes, `/swiss-cheese:loop <task>` for autonomous work.
