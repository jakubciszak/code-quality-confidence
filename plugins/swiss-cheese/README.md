# swiss-cheese

Layered defense (Swiss Cheese model) for agentic coding in Claude Code.

Each quality gate is a slice of cheese with holes. Defects ship only when holes align across **all** slices — so the plugin stacks cheap, diverse, imperfect layers and keeps their holes from lining up. Two design rules govern everything:

1. **Progressive disclosure.** A session sees only each skill/agent's one-line `description` until a task matches it. Rule catalogs, vendor lists and patterns live in `references/` and load on demand. The costliest bytes are always-on descriptions, so there is **one** review-orchestrator skill instead of seven auto-invoked review agents.
2. **Determinism where you need a guarantee; model judgment only for vigilance.** Anything that must be repeatable and auditable is a stdlib-only Python script (exit code, hook). The model can only ever *raise* coverage, never cut what a rule required.

## Quick start

```
/plugin marketplace add jakubciszak/code-quality-confidence
/plugin install swiss-cheese@code-quality-confidence
```

Then in your project:

```
/swiss-cheese:init          # probe repo + detect runners, choose layers, write config v2
/swiss-cheese:intent        # reconstruct a ticket into a contract before coding
/swiss-cheese:review        # layered multi-lens review of your current diff
/swiss-cheese:loop <task>   # work autonomously, passing every layer in a loop
/swiss-cheese:pair          # devil's-advocate questions on your change
```

## Skills (native — not legacy `commands/`)

Interactive entry points are **skills**. The consciously-invoked ones set `disable-model-invocation: true` so they never fire on their own.

- **`init`** — probes with `repo_probe.py` and `runner_detector.py` (detects the exact `test`/`lint`/`typecheck` command via Makefile → package.json → composer → pyproject → justfile → Taskfile → docker-compose → binaries, instead of guessing). Proposes `high_risk_paths` from a directory probe and a `permissions.deny` stanza — **never** editing `.claude/settings.json` itself.
- **`review`** — orchestrator: `diff_snapshot` → `run_guards` → `select_agents` (a deterministic lens **floor**) → parallel lens subagents on the **redacted** diff → one deduplicated, severity-ranked report.
- **`loop`** — implement → `check_layers.py --fast` → guards → review → fix → repeat, bounded by `loop.max_iterations`. Never weakens a layer to pass it.
- **`intent`** (Haiku) — reconstructs intent, acceptance criteria, test plan, scope guards, risk class, and a ready `AI-disclosure` block. Stops; writes no code.
- **`pair`** (Sonnet) — a numbered list of hard questions that try to break the approach; read-only, so it physically can't write code.
- **`layer`**, **`status`**, **`knowledge`**, **`audit`** — manage the stack, render it, wire task sources, grade the knowledge layers.

## The deterministic pre-LLM layer: guards

Before any model is spent, `run_guards.py` scans the diff **as data, never executing it**, and writes `guards.json`:

| guard | catches | severity |
|---|---|---|
| `injection` | prompt-injection tokens, comment-and-control phrasings, edits to agent-control files (`.claude/**`, `CLAUDE.md`, `*mcp.json`) | blocker / medium / high |
| `secrets` | credentials — and **redacts them** into `diff.redacted.patch` (what review lenses read) | blocker / high |
| `policy` | ≥2000 LOC (blocker) / ≥500 (medium); high-risk path without `human-reviewed`; >100 LOC without `AI-disclosure` | blocker / high / medium |
| `slopsquat` | typosquatted deps (offline edit-distance to popular packages) and, opt-in online, missing/too-new registry records | high / medium |
| `high_risk` | changes under `high_risk_paths` → forces `escalate` | high |

Blockers are enforced at **commit time** by a `PreToolUse` hook (`guard_hook.py`) — a hard `exit 2` with zero token cost. Every internal error is `exit 0`: a layer may have holes, but it must never kill the session.

## The review layer is itself Swiss cheese

`select_agents.py` is a pure function of `manifest.json` + `guards.json`. It returns **two separate fields**, and the split is the point:

- `required` — an **unremovable** lens set, computed by rule (code → `core`; code without tests → `tests`; high-risk path or ≥8 files → `staff`; API surface → `architecture`; dependency change → slopsquat-heavy `security` + `staff`; …). Never empty for a non-empty diff.
- `escalation_allowed` — whether the model may **add** lenses when the diff smells riskier than the metrics caught. The model's only lever raises vigilance; it can never lower the floor.

Lenses (`review-core`, `-security`, `-tests`, `-performance`, `-architecture`, `-docs`, `-staff`) are read-only (`tools: Read, Grep, Glob`), spawned **explicitly** in parallel, each returning only its verdict — independent slices don't infect each other's reasoning. On a high-risk path, `architecture` and `staff` escalate to **Opus**. `adr_loader.py` ranks ADRs by token overlap with the diff and hands the deep lenses only the top-N paths.

Every finding carries a fifth field, **`verification`**: the test/assertion/lint rule that would catch it (or `manual: <why>`) — operationalizing "don't ask the model to verify; ask it to write a script that verifies."

## Config v2

`.swiss-cheese/config.json`: `layers` is an object keyed by id, each with `mode: auto | comment | skip`. Global gating is `block_at` / `warn_at` on the `blocker | high | medium | low` scale. `check_layers.py` reports every layer as **passed | failed | skipped** — a missing binary is `skipped`, never a silent pass — and computes `ok` **only from `auto` layers that `failed`**. A v1 config still runs (defaults + a one-line nudge to re-init).

## Audit log — split by observability

`audit_log.py` appends to `.swiss-cheese/audit/YYYY-MM.jsonl` (no tokens; the plugin never reads it back into a model):

- **System events** the harness *can* see are written by a **hook** — an uninterpreted, complete backbone: `agent_spawned`, `layer_result`, `policy_block`, `guard_finding`.
- **Interpretive events** only the model knows the *why* of are written by the model through the script, **fail-closed**: a review finding is retired **only** after a `finding_dismissed` entry — a forgotten log line leaves the finding *active* (visible and safe), not silently dropped.

## Agent memory

Lenses ship with `memory: project` (committed under `.claude/agent-memory/`, shared team knowledge). `MEMORY.md` indexes topic files by prefix (`feedback_`, `project_`, `reference_`, `arch_`, `patterns_`), unified on the `metadata.type` key. Agents **revise** their own entries (`**UPDATE (<ref>):**`, `**STALE:**`, `**RESOLVED:**`) and write **only** on three hard triggers: a finding dismissed, a durable convention discovered, or an entry gone stale.

## Project state

```
.swiss-cheese/
  config.json          # the defense stack, schema v2 (see templates/config.sample.json)
  runners.json         # detected run commands per task
  knowledge.json       # task/domain knowledge sources
  runs/latest/         # diff.patch + diff.redacted.patch + manifest.json + guards.json
  audit/YYYY-MM.jsonl  # append-only audit trail
.claude/
  agent-memory/        # persistent per-lens memory
```

`config.json`, `runners.json`, `knowledge.json` and `.claude/agent-memory/` belong in the repo; `.swiss-cheese/runs/` is gitignored.

## Sources

- kenimo49, [The Swiss Cheese Model of AI Security](https://dev.to/kenimo49/the-swiss-cheese-model-of-ai-security-why-single-layer-defense-always-fails-258l)
- geekpulp, [Swiss Cheese Model of Agentic Coding](https://geekpulp.co.nz/2026/04/25/swiss-cheese-model-of-agentic-coding/)
- James Reason, [Swiss cheese model](https://en.wikipedia.org/wiki/Swiss_cheese_model)
