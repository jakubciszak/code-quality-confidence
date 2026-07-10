---
name: swiss-cheese-model
description: Domain knowledge of the Swiss Cheese model applied to agentic coding and AI security — layer catalog, hole analysis, risk profiles. Load when initializing layers, discussing defense-in-depth, choosing which layers a project needs, or explaining why a single gate failed to catch a defect.
---

# The Swiss Cheese model for agentic coding

Origin: James Reason's accident-causation model (aviation, healthcare). Each defense layer is a slice of Swiss cheese — it has holes. A defect causes harm only when holes in **every** layer line up. Corollary that drives everything this plugin does:

> You don't need perfect defenses. You need enough imperfect ones that the holes never align.

Two source framings this plugin merges:

- **AI security** (dev.to, kenimo49): AI static analysis → dynamic testing (DAST/chaos) → circuit breakers & fail-safe patterns → human review with context. Key insight: every layer hallucinates, misses, or fatigues — plan for it. High-risk systems (payments, auth) get all layers; low-risk gets a justified subset.
- **Agentic coding** (geekpulp.co.nz): agent instructions → linting → agent hooks → pre-commit → CI → automated review → human review. Key insight: agentic coding is a *systems* problem, not a prompt-engineering problem; feed failures back to the agent early and often.

## Operating rules

1. **Every layer has named holes.** When adding a layer, record what it will miss (`"holes"` field in config). Unnamed holes are the ones that align silently.
2. **Cheapest mechanism first.** scripted (deterministic, zero tokens) → hook (per-edit) → agent (LLM judgment) → human. Never spend an agent on what a script can decide. Never spend a human on what an agent catches reliably.
3. **Independence matters.** Layers that share a failure mode (two LLM reviews with the same prompt) are one slice pretending to be two. Diversify mechanism, not just count.
4. **Fail closed on high-risk paths.** An erroring security check that lets the change through is a hole that spans the whole slice.
5. **Feedback beats gatekeeping.** A layer that reports a defect to the agent seconds after the edit (hooks) is worth more than the same check run once at the end.
6. **Risk-profile the stack.** `high` (payments, auth, PII): all layers incl. dynamic testing, blocking review. `standard`: scripted layers + auto-selected agent review + docs discipline. `low`: lint, tests, advisory review.

## Layer catalog

The full catalog with per-layer semantics, default commands, and named holes is in [../../references/layer-catalog.md](../../references/layer-catalog.md). Read it when configuring or explaining specific layers.

## Project state contract

- `.swiss-cheese/config.json` — the stack definition, schema **v2** (see `templates/config.sample.json`). `layers` is an object keyed by id; each layer has `mode: auto | comment | skip`. Global gating is `block_at` / `warn_at` on the `blocker | high | medium | low` scale.
- `.swiss-cheese/runners.json` — detected run commands per task (from `runner_detector.py`).
- `.swiss-cheese/knowledge.json` — task/domain knowledge sources (Jira, Linear, MCP servers).
- `.swiss-cheese/runs/latest/` — last run snapshot: `diff.patch`, `diff.redacted.patch` (what review lenses read), `manifest.json`, `guards.json`. Produced by `diff_snapshot.py` + `run_guards.py`, shared by all lenses.
- `.swiss-cheese/audit/YYYY-MM.jsonl` — append-only audit log (hook-written backbone + model-written interpretive entries).

## Diagnosing an escape

When a defect reached production/merge despite the stack, walk the slices in order and label each: *hole* (layer can't catch this class — expected), *misconfiguration* (should have caught it, wasn't set up to), or *bypass* (was skipped). One escape usually justifies at most one new layer or one narrowed hole — resist stacking ceremony after every incident.
