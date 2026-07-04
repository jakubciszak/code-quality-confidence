---
description: Work autonomously on a task, passing every Swiss Cheese layer in a loop until the change is clean
argument-hint: "<task description or issue reference>"
---

Autonomous **layer loop**: implement `$ARGUMENTS`, then push the change through the defense stack repeatedly until every layer passes or the iteration budget runs out. You are the operator; the layers are the safety system.

Requires an initialized project (`.swiss-cheese/config.json`). If missing, tell the user to run `/swiss-cheese:init` first and stop.

If `$ARGUMENTS` is empty, ask what to work on — or, if `.swiss-cheese/knowledge.json` defines a task source (Jira/Redmine/etc. via MCP), offer to pull the next assigned task from there.

## Loop protocol

Read `loop.order` and `loop.max_iterations` from the config. Then:

**0. Plan briefly** — restate the task, identify the files involved, note the acceptance criteria.

**1. Implement** the task (or the fixes from the previous iteration).

**2. Scripted layers gate** — one call, not N:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/check_layers.py" --fast
```

If it fails: fix exactly what `output_tail` shows and go back to step 2. Feed problems back early — this is the cheapest layer to iterate on. After fast layers are green, run once more **without** `--fast` to include slow suites.

**3. Review layer gate** — only when all scripted layers pass:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/diff_snapshot.py"
```

Fan out the recommended review agents exactly as `/swiss-cheese:review` does (parallel, shared diff file, no diff in prompts). Apply the fixes for `blocker` and `high` findings; use judgment on `medium`/`low` (fix if cheap, otherwise record them in the final report).

**4. Converge or iterate** — if review produced blockers/highs, count an iteration and return to step 2. Stop when:
- all scripted layers pass AND review has no blocker/high findings → **done**, or
- `max_iterations` reached → stop and report honestly what still fails.

## Rules

- Never weaken a layer to pass it (don't skip tests, don't lower lint severity, don't edit the config mid-loop). If a layer seems wrong, finish the loop and report it.
- Keep a running one-line log per iteration: `iter N: lint ✅ tests ❌(2) → fixed → review: 1 high`.
- When you reject a review finding as false positive/accepted-by-design, tell that agent to record the decision in its memory (see the learning loop in `/swiss-cheese:review`) — otherwise the next iteration re-litigates it.
- Final report: what was built, iterations used, per-layer final status, unresolved findings, and any layer that repeatedly caught mistakes (that layer is earning its place in the stack).
