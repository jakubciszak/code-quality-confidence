---
name: loop
description: Autonomous work loop — implement a task, then drive it through the Swiss Cheese layers until clean. Use for "work on X and keep it passing the gates" style requests on an initialized project.
---

# Swiss Cheese layer loop

Implement `$ARGUMENTS`, then push the change through the defense stack repeatedly until every layer passes or the iteration budget runs out. You are the operator; the layers are the safety system.

Requires an initialized project (`.swiss-cheese/config.json`). If missing, tell the user to run `/swiss-cheese:init` first and stop. If `$ARGUMENTS` is empty, ask what to work on — or, if `.swiss-cheese/knowledge.json` names a task source (Jira/Linear via MCP), offer to pull the next assigned task **from the main session** (subagents can't reach MCP).

## Loop protocol

Read `loop.order` and `loop.max_iterations` from the config.

**0. Plan briefly** — restate the task, the files involved, the acceptance criteria.

**1. Implement** the task (or the previous iteration's fixes).

**2. Scripted layers gate — one call, not N:**

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/check_layers.py" --fast
```

`ok` is computed only from `auto` layers that `failed` (skipped/comment layers never break it). If not `ok`, fix exactly what `output_tail` shows and repeat step 2 — this is the cheapest layer to iterate on. Once fast layers are green, run once more **without** `--fast` for slow suites.

**3. Guards + review gate — only when scripted layers pass:**

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/diff_snapshot.py"
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run_guards.py" --run-dir .swiss-cheese/runs/latest
```

If guards report `blocked`, resolve those first (the commit hook will block anyway). Then fan out the review lenses exactly as the `review` skill does (select_agents floor → parallel subagents on the redacted diff). Apply fixes for `blocker`/`high`; use judgment on `medium`/`low`.

**4. Converge or iterate** — if review produced blockers/highs, count an iteration and return to step 2. Stop when scripted layers pass AND review has no blocker/high → **done**; or `max_iterations` reached → stop and report honestly what still fails.

## Rules

- Never weaken a layer to pass it (don't skip tests, lower severity, or edit the config mid-loop). If a layer seems wrong, finish and report it.
- One-line log per iteration: `iter N: lint ✅ tests ❌(2) → fixed → guards clean → review: 1 high`.
- A dismissed review finding is only retired after an `audit_log.py finding_dismissed` entry (fail-closed) — otherwise it stays active and the next iteration re-litigates it.
- Final report: what was built, iterations used, per-layer final status, unresolved findings, and any layer that repeatedly caught mistakes.
