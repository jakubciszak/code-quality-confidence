# code-quality-confidence

A **Claude Code plugin marketplace** built around the [Swiss Cheese model](https://en.wikipedia.org/wiki/Swiss_cheese_model) of layered defense for agentic coding.

> You don't need perfect defenses. You need enough imperfect ones that the holes never align.

Every quality gate — linting, tests, hooks, AI review, human review — is a slice of Swiss cheese: useful, but full of holes. A defect ships only when the holes in *every* slice line up. This marketplace distributes tooling that stacks those slices for you, cheaply.

```
  defect ──▶ ░ instructions ░──▶ ░ lint ░──▶ ░ hooks ░──▶ ░ tests ░──▶ ░ agent review ░──▶ ░ human ░──▶ ✗ stopped
                 ○   ○              ○            ○  ○         ○             ○    ○             ○
                (holes)           (holes)      (holes)      (holes)       (holes)           (holes)
```

Based on:
- [The Swiss Cheese Model of AI Security](https://dev.to/kenimo49/the-swiss-cheese-model-of-ai-security-why-single-layer-defense-always-fails-258l) (kenimo49)
- [Swiss Cheese Model of Agentic Coding](https://geekpulp.co.nz/2026/04/25/swiss-cheese-model-of-agentic-coding/) (geekpulp)
- [Swiss cheese model](https://en.wikipedia.org/wiki/Swiss_cheese_model) (James Reason)

## Installation

In Claude Code:

```
/plugin marketplace add jakubciszak/code-quality-confidence
/plugin install swiss-cheese@code-quality-confidence
```

If your environment can't fetch marketplaces from GitHub directly, clone first:

```bash
git clone https://github.com/jakubciszak/code-quality-confidence.git
```

```
/plugin marketplace add /path/to/code-quality-confidence
/plugin install swiss-cheese@code-quality-confidence
```

## Plugins

### `swiss-cheese` — layered defense for agentic coding

Native **skills** (not legacy `commands/`). Consciously-invoked ones set `disable-model-invocation: true`.

| Skill | What it does |
|---|---|
| `/swiss-cheese:init` | Probes the repo (`repo_probe.py`) and **detects how to run tools** (`runner_detector.py`: Makefile → package.json → composer → pyproject → justfile → Taskfile → docker-compose → binaries), proposes `high_risk_paths` and a `permissions.deny` stanza, writes config v2. Never edits `.claude/settings.json` itself. |
| `/swiss-cheese:intent` | Reconstructs a ticket into intent, acceptance criteria, test plan, scope guards, risk class, and an `AI-disclosure` block — then stops, writing no code (Haiku). |
| `/swiss-cheese:review` | `diff_snapshot` → deterministic **guards** → `select_agents` (an unremovable lens floor) → independent read-only lens subagents on the **redacted** diff, in parallel → one ranked report. |
| `/swiss-cheese:loop <task>` | Implement → `check_layers.py --fast` → guards → review → fix → repeat until green or the iteration budget runs out. |
| `/swiss-cheese:pair` | A numbered list of hard, break-it questions on your change (Sonnet, read-only — can't write code). |
| `/swiss-cheese:layer` · `:status` · `:knowledge` · `:audit` | Manage the stack, render it, wire task sources, grade the knowledge layers. |
| `/swiss-cheese:custom-layer` | A five-step methodology for building a defense layer the catalog doesn't cover — name the failure mode, pick the cheapest mechanism, implement, analyze the new holes, test. |

Two further skills are **model-invoked domain knowledge** rather than slash commands: **`swiss-cheese-model`** (the layer catalog, hole analysis, and risk profiles, loaded when reasoning about defense-in-depth or explaining why a gate missed a defect) and **`custom-layer`** (also reachable directly, above). A session sees only their one-line description until a task matches, so they carry no always-on cost.

**Deterministic pre-LLM guards.** `run_guards.py` (stdlib-only) scans the diff **as data, never executing it** — `injection`, `secrets` (with redaction into `diff.redacted.patch`), `policy` (LOC/marker thresholds), `slopsquat` (typosquat/hallucinated deps), `high_risk`. Blockers are enforced at commit time by a `PreToolUse` hook (`exit 2`, zero tokens). Every internal error is `exit 0` — a layer may have holes, but it never kills the session.

**A deterministic review-lens floor.** `select_agents.py` returns `required` (unremovable, rule-computed, never empty for a real diff) separately from `escalation_allowed` (whether the model may *add* lenses). The boundary lives in the data structure, not in a "please don't remove" prompt. Read-only lenses (core/security/tests/performance/architecture/docs/staff) run in parallel; high-risk paths escalate architecture/staff to Opus; every finding carries a `verification` field.

**Config v2 & fail-closed audit.** `layers` keyed by id with `mode: auto | comment | skip`; `ok` counts only `auto` layers that `failed`; a missing binary is `skipped`, never a silent pass. The audit log's system backbone is hook-written; interpretive entries are model-written and fail-closed — a finding stays active until a `finding_dismissed` line exists.

**Agents remember your project.** Read-only lenses carry `memory: project` (committed under `.claude/agent-memory/`) with a revalidation protocol (`UPDATE`/`STALE`/`RESOLVED`) and three hard write triggers — so each run is sharper than the last.

See [plugins/swiss-cheese/README.md](plugins/swiss-cheese/README.md) for full docs, the layer catalog, and the config schema.

## Development

The repository eats its own cooking — two CI slices guard every PR (`.github/workflows/ci.yml`):

- **Unit tests** for all plugin scripts: `pip install pytest && pytest -q` (covering the config loader, layer engine, every guard + redaction, the deterministic lens selector, runner detection, ADR ranking, the audit log's fail-closed contract, the commit gate, and the permissions-stanza generator)
- **Manifest validation**: `claude plugin validate .` and `claude plugin validate plugins/swiss-cheese`

## Repository layout

```
.claude-plugin/marketplace.json      # the marketplace catalog
.github/workflows/ci.yml             # CI: pytest + claude plugin validate
tests/                               # unit tests for the plugin scripts
plugins/
  swiss-cheese/
    .claude-plugin/plugin.json       # plugin manifest
    skills/                          # native skills: review, loop, intent, pair, init, layer, custom-layer, swiss-cheese-model, ...
    agents/                          # read-only subagents: lens set (review-*), intent-agent, pair-agent, repo-analyst
    scripts/                         # stdlib-only Python: config, guards/, diff, select, runners, audit
    references/                      # layer catalog, injection patterns, popular-packages list (load on demand)
    templates/                       # config v2 sample, ADR, checklist, pre-commit config, CLAUDE.md governance
    hooks/hooks.json                 # PreToolUse guards + commit gate; PostToolUse agent-hooks + audit
    MEMORY.md                        # agent-memory index & protocol
```

## License

MIT
