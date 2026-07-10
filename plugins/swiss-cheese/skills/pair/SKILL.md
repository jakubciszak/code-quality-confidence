---
name: pair
description: Devil's-advocate pairing on the current change — a numbered list of hard questions that try to break the approach. Invoke consciously when you want your design challenged.
disable-model-invocation: true
---

# Pair — devil's advocate

Challenge the current change or plan. Your job is to try to break it, then report what you found — not to fix it.

Spawn the pair subagent with the Agent tool, `subagent_type = swiss-cheese:pair-agent` (Sonnet, tools `Read, Grep, Glob` — it physically cannot write code, which is the point). Pass it the task/plan context and, if a review run exists, the path to `.swiss-cheese/runs/latest/diff.redacted.patch`.

It returns — and you present — a **numbered list of pointed questions**, hardest first:

- Where does this break under load, concurrency, partial failure, or hostile input?
- What assumption is load-bearing and unstated? What happens when it's false?
- What's the rollback story? What's irreversible here?
- What existing mechanism does this duplicate or contradict?
- Which acceptance criterion is *not actually* covered by the test plan?

If, after genuinely trying, it cannot find a real weakness, it ends with exactly: **"I tried to break it and couldn't."** — a signal of confidence, not a filler.

Present the questions verbatim and let the user decide which to act on. Do not answer them yourself unless asked.
