---
description: Analyze this repository and initialize Swiss Cheese defense layers (config, skills, agents, docs)
argument-hint: "[risk profile: low|standard|high]"
---

You are initializing the **Swiss Cheese model** of layered defense in this repository.
Core principle: *you don't need perfect defenses — you need enough imperfect ones that the holes never align.*

Follow this procedure strictly and stay token-frugal: the Python probe replaces manual exploration.

## 1. Probe the repository (one call, no manual exploration)

Run:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/repo_probe.py" .
```

Parse the JSON. Only Read individual files (README, CI config, pyproject/package.json) if the probe leaves a decision genuinely ambiguous — never walk the tree yourself.

If `swiss_cheese.initialized` is already `true`, tell the user and switch to *update mode*: show current layers vs. findings and only propose deltas.

## 2. Interview the user

Use AskUserQuestion (one round, max 4 questions) to establish:

1. **Risk profile** — `low` / `standard` / `high` (payments, auth, PII ⇒ high). Skip if given in $ARGUMENTS.
2. **Which predefined layers to enable** (multiSelect) — pre-select sensible defaults based on the probe (e.g. don't offer `typecheck` for a shell-only repo; offer `dynamic-testing` only for high risk).
3. **Review style** — strictness of the multi-agent review layer: `blocking` (findings must be fixed), `advisory`, or `severity-gated` (block only on high severity).
4. **Where task knowledge lives** — Jira, Redmine, Linear, GitHub Issues, Azure DevOps, none/other. If they pick one, tell them `/swiss-cheese:knowledge` will wire it up (offer to run it at the end).

## 3. Generate the defense stack

Consult the layer catalog in the `swiss-cheese-model` skill (`layer-catalog.md`) for layer semantics. Then write **`.swiss-cheese/config.json`**:

- `risk_profile`, `review.style` from answers.
- One entry per chosen layer. For `scripted` layers, derive real commands from the probe (detected linters, typecheckers, test frameworks). Verify each command actually runs (`--version` or a dry form) before committing it to config; mark slow suites `"fast": false`.
- `review` layer: `"type": "agents"`, `"selection": "auto"`, agents `["correctness","security","architecture","performance","tests","docs"]`.
- `agent-hooks` layer (if chosen): map detected file extensions to fast per-file checks, e.g. `{".py": "ruff check --quiet {file}"}`. This activates the plugin's PostToolUse hook automatically — no settings edit needed.
- `loop`: order `[fast scripted → slow scripted → review]`, `max_iterations: 5`.

Use `templates/config.sample.json` in the plugin as the structural reference.

## 4. Generate supporting artifacts (only what's missing)

Based on probe results, create — asking no further questions:

- **CLAUDE.md section** (instructions layer): append/create a `## Swiss Cheese layers` section from `templates/claude-md-section.md`, filled with the actual stack, so every future agent session knows the gates it must pass.
- **ADR scaffold** (docs layer): if no ADR dir exists, create `docs/adr/` with `0001-record-architecture-decisions.md` from `templates/adr-template.md`.
- **Review checklist** (human-review layer): `docs/review-checklist.md` from `templates/review-checklist.md`, adapted to the detected stack.
- **Pre-commit config** (pre-commit layer): if chosen and missing, generate `.pre-commit-config.yaml` (or husky/lint-staged for Node repos) wired to the same commands as the scripted layers — same checks, earlier slice of cheese.

Do NOT copy the plugin's review agents into the project — they ship with the plugin and are already available as `swiss-cheese:review-*`.

**Agent memory**: the review agents use `memory: project` and will accumulate project knowledge in `.claude/agent-memory/`. Make sure this path is NOT gitignored (it's meant to be committed — that's how the team shares what the agents learned), while `.swiss-cheese/runs/` IS gitignored. Optionally seed `.claude/agent-memory/review-architecture/MEMORY.md` with 3–5 bullet design decisions you can infer from the probe (framework, module layout, persistence) — one line each, so the architecture agent starts warm.

## 5. Report

Run:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/layer_status.py"
```

Show its output, then add:
- **Documentation gaps** the probe revealed (no CONTRIBUTING, no ARCHITECTURE.md, empty README, no ADRs, no PR template, no CODEOWNERS) with a one-line "why it matters" each — recommend, don't create unless asked.
- Next steps: `/swiss-cheese:review` after changes, `/swiss-cheese:loop <task>` for autonomous work, `/swiss-cheese:layer` for custom layers, `/swiss-cheese:knowledge` for task-source wiring.
