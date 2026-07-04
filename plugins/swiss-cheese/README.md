# swiss-cheese

Layered defense (Swiss Cheese model) for agentic coding in Claude Code.

Each quality gate is a slice of cheese with holes. Defects ship only when holes align across **all** slices — so the plugin's job is to stack cheap, diverse, imperfect layers and keep their holes from lining up.

## Quick start

```
/plugin marketplace add jakubciszak/code-quality-confidence
/plugin install swiss-cheese@code-quality-confidence
```

Then in your project:

```
/swiss-cheese:init          # analyze repo, choose layers, generate config + artifacts
/swiss-cheese:review        # smart multi-agent review of your current changes
/swiss-cheese:loop <task>   # work autonomously, passing every layer in a loop
```

## Commands

- **`/swiss-cheese:init [low|standard|high]`** — probes the repo with `scripts/repo_probe.py` (languages, linters, tests, CI, docs, ADRs — one JSON, zero exploration), asks about risk profile / layers / review style / task sources, then writes `.swiss-cheese/config.json` and generates only what's missing: CLAUDE.md guardrail section, `docs/adr/` scaffold, review checklist, pre-commit config.
- **`/swiss-cheese:review [--base <ref>] [--staged] [--all] [--only a,b]`** — `scripts/diff_snapshot.py` writes **one** `diff.patch` + `manifest.json` and deterministically picks which review agents this change warrants (security only when security-relevant paths/deps/risky patterns are touched; performance only for DB/hot-path/large changes; tests always when code changed without tests; …). Selected agents run in parallel, all reading the same file. Output: one deduplicated, severity-ranked report plus which slices ran/were skipped and why.
- **`/swiss-cheese:loop <task>`** — implement, then iterate: `check_layers.py --fast` → fix → full gates → agent review → fix blockers/highs → repeat (bounded by `loop.max_iterations`). Never weakens a layer to pass it. Can pull tasks from configured knowledge sources (Jira/Redmine via MCP).
- **`/swiss-cheese:layer [add <id> | custom | list]`** — predefined layers from the catalog, or a guided custom-layer wizard: name the failure mode → pick the cheapest mechanism (script > hook > agent > process) → build it together → name its holes → test it on a real defect.
- **`/swiss-cheese:audit`** — grades the knowledge layers (README, CONTRIBUTING, ARCHITECTURE, ADRs, PR template, CODEOWNERS, SECURITY.md, review style) and proposes the top 3 fixes by risk-reduction-per-effort. Proposes concrete first ADRs from decisions already visible in the code.
- **`/swiss-cheese:knowledge [tracker]`** — asks where tasks and domain knowledge live, then *searches* for integrations (already-connected MCP servers → registry/plugin search → web) instead of guessing; records the result in `.swiss-cheese/knowledge.json` and CLAUDE.md.
- **`/swiss-cheese:status`** — renders the stack, disabled layers, and missing catalog layers via `scripts/layer_status.py`.

## The review layer is itself Swiss cheese

| Sub-agent | Lens | Runs when |
|---|---|---|
| `review-correctness` | logic, edge cases, error handling, races | any code/db/config change |
| `review-security` | injection, authz, secrets, deps, fail-open | security paths, deps, CI, risky added lines |
| `review-architecture` | boundaries, coupling, ADR consistency, API design | new modules, many files, deps, API surface |
| `review-performance` | N+1, unbounded IO, hot-loop waste | DB changes, hot-path modules, large diffs |
| `review-tests` | coverage gaps, weakened/deleted tests, mock theater | code without test changes, or tests changed |
| `review-docs` | doc drift, missing ADRs, comment rot | docs changed, or API changed without docs |

Selection lives in `diff_snapshot.py` (deterministic, auditable — the manifest records every skip with a reason). Override with `--all` or `--only`.

## Agents learn your project (persistent memory)

Every agent ships with `memory: project`: a persistent directory under **`.claude/agent-memory/<agent>/`** that survives across sessions and is meant to be **committed**, so the whole team (and CI sessions) share what the agents learned.

What accumulates there, per slice:

- `review-architecture` — the module map, dependency rules, a one-line digest per ADR, accepted exceptions → it *enforces* your design decisions instead of rediscovering them each review
- `review-security` — where auth lives, which sanitization helpers are trusted, traced sinks, confirmed false-positive patterns (mechanisms only — never secret values)
- `review-correctness` — verified invariants, chronically fragile modules, recurring bug classes
- `review-performance` — which paths are actually hot vs. cold, scale facts, past incidents
- `review-tests` — test conventions, under-tested modules, rejected demands
- `review-docs` — the documentation map, drift-prone sections
- `repo-analyst` — stable structural facts with `file:line` anchors

The learning loop is explicit: when you dismiss a finding as false positive or accepted-by-design during `/swiss-cheese:review` or `/swiss-cheese:loop`, the orchestrator tells the agent to record that decision — so the same pattern is not re-flagged next time. Memory doubles as a token saver: a warm agent greps its MEMORY.md instead of re-exploring the codebase.

Housekeeping: agents keep MEMORY.md short and curated (the harness injects only its first ~200 lines), never write secrets into it, and never touch project files — the memory directory is their only writable location.

## Token frugality rules baked into the plugin

1. Deterministic work is Python (stdlib only): probing, diffing, classification, agent selection, gate execution, status.
2. The diff is generated once per review and shared as a file; agent prompts contain a path, never content.
3. Agents are selected by change content; a docs-only diff never pays for six agents.
4. Scripted gates run as one `check_layers.py` call returning compact JSON with only failure tails.
5. Review agents are read-only, lane-scoped, and output a fixed one-line-per-finding format.

## Project state

```
.swiss-cheese/
  config.json          # the defense stack (see templates/config.sample.json)
  knowledge.json       # task/domain knowledge sources
  runs/latest/         # last review: diff.patch + manifest.json
.claude/
  agent-memory/        # persistent per-agent memory (design decisions, patterns)
```

Add `.swiss-cheese/runs/` to `.gitignore`; `config.json`, `knowledge.json` and `.claude/agent-memory/` belong in the repo.

### config.json layer types

| type | meaning | executed by |
|---|---|---|
| `scripted` | shell command, exit code = verdict | `check_layers.py`, pre-commit, CI |
| `hook` | per-edit command via `on_edit` map | plugin PostToolUse hook (`hook_gate.py`) |
| `agents` | review sub-agents | `/swiss-cheese:review`, loop |
| `knowledge` | docs/ADR discipline | audit + review-docs agent |
| `process` | human procedures (checklists) | humans |
| `custom` | anything with a named failure mode | per its mechanism |

Every layer should declare `"holes"` — what it is known to miss. Unnamed holes are the ones that align.

## The agent-hooks layer

The plugin registers a `PostToolUse` hook on `Write|Edit`. It is a **silent no-op** unless the current project's config contains an enabled `agent-hooks` layer with an `on_edit` map, e.g.:

```json
{"id": "agent-hooks", "type": "hook", "enabled": true,
 "on_edit": {".py": "ruff check --quiet {file}", ".ts": "npx eslint {file}"}}
```

On failure the check's output is fed back to the agent immediately (exit 2), so the defect is fixed seconds after the edit instead of surfacing at review. Internal errors never block the session — this slice has holes by design; the later slices cover them.

## Sources

- kenimo49, [The Swiss Cheese Model of AI Security](https://dev.to/kenimo49/the-swiss-cheese-model-of-ai-security-why-single-layer-defense-always-fails-258l)
- geekpulp, [Swiss Cheese Model of Agentic Coding](https://geekpulp.co.nz/2026/04/25/swiss-cheese-model-of-agentic-coding/)
- James Reason, [Swiss cheese model](https://en.wikipedia.org/wiki/Swiss_cheese_model)
