---
description: Multi-agent Swiss Cheese code review — one shared diff, agents picked by what actually changed
argument-hint: "[--base <ref>] [--staged] [--all] [--only agent1,agent2]"
---

Run the **review layer**: a composite slice of cheese made of specialized review agents.
Token rules — these are hard constraints, not suggestions:

1. The diff is generated **exactly once** by the script. Never run `git diff` yourself and never paste diff content into agent prompts — agents Read the shared file.
2. Spawn **only** the agents the manifest recommends (unless the user passed `--all` or `--only`).
3. Spawn all selected agents **in parallel, in one message**.

## 1. Snapshot the diff

Run (forward any of `--base/--staged/--all` from `$ARGUMENTS`):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/diff_snapshot.py" $ARGUMENTS
```

The JSON on stdout contains `diff_path`, per-file stats/categories, `recommended_reviews` (with reasons) and `skipped_reviews`. If `empty: true`, report that and stop.

If the user passed `--only agent1,agent2`, that overrides the recommendation entirely.

## 2. Fan out the review agents

For each selected agent, use the Agent tool with `subagent_type` = `swiss-cheese:review-<name>` (e.g. `swiss-cheese:review-security`). Every prompt is the same minimal envelope:

```
Review the change at <diff_path> (manifest: <same dir>/manifest.json).
Selection reason: <reason from manifest>.
Consult your agent memory for project knowledge relevant to the touched files first.
Read the diff from the file; open source files only to confirm suspected issues.
Return findings in your required output format. If nothing found, return "NO FINDINGS".
Afterwards, update your agent memory with durable learnings per your memory protocol.
```

Nothing else — no diff content, no file lists (they are in the manifest on disk).

## 3. Merge and report

Collect all findings and produce ONE consolidated report:

- Deduplicate overlapping findings (same file+line from two agents ⇒ keep the more severe, note both lenses).
- Sort by severity: `blocker`, `high`, `medium`, `low`.
- Format each as: `severity` · `file:line` · issue · suggested fix · `(agent)`.
- End with the coverage summary: which agents ran and why, which were skipped and why (straight from the manifest) — this shows which cheese slices were active for this change.

**Close the learning loop.** If the user dismisses a finding as a false positive or as accepted-by-design, send one short follow-up to that agent (SendMessage, or a note in the next invocation): "Finding <file:line — issue> was rejected because <reason>; record this in your memory so you don't re-flag the pattern." The agents keep project decisions in `.claude/agent-memory/` — this is how each review gets sharper than the last.

If `.swiss-cheese/config.json` sets `review.style`:
- `blocking` — state clearly the change should not merge until blockers/highs are fixed; offer to fix them now.
- `severity-gated` — same, but only for `blocker`.
- `advisory` — findings are recommendations.
