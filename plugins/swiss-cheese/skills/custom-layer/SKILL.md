---
name: custom-layer
description: Methodology for designing and building a custom Swiss Cheese defense layer — failure-mode definition, mechanism selection, implementation, hole analysis, testing. Load when the user wants a layer the catalog doesn't cover or invokes /swiss-cheese:layer custom.
---

# Building a custom defense layer

A layer earns its place by catching a **named class of defect** that current layers let through. Walk the user through these five steps; do not skip ahead to implementation.

## 1. Name the failure mode

Ask until you can fill in this sentence concretely:

> "This layer catches **[defect class]**, which today would slip through because **[which existing layers miss it and why]**."

Examples of good failure modes: "SQL migrations that lock tables >1M rows", "user-facing strings added without i18n keys", "endpoints returning PII without the audit decorator", "GPL-licensed transitive dependencies". Bad: "bad code", "security issues" (too broad — that's a stack, not a layer).

If the failure mode is actually covered by a catalog layer, say so and configure that instead.

## 2. Choose the cheapest mechanism that works

In strict order — justify any step down the list:

| Mechanism | Use when | Runtime cost |
|---|---|---|
| `scripted` — a deterministic script/command | the rule can be decided by code: grep-able patterns, AST checks, schema diffs, license lists | zero tokens |
| `hook` — per-edit check via `on_edit` | same, but worth catching seconds after each edit of matching files | zero tokens, instant feedback |
| `agents` — a review sub-agent | the check genuinely requires judgment: "is this name misleading", "does this contradict the ADR" | tokens per review |
| `knowledge`/`process` — docs, checklist item | the check is for humans, or context for future sessions | zero |

**Everything scriptable must be scripted** — prefer a 30-line Python (stdlib-only, mirroring the plugin's scripts: JSON out, exit code = verdict) over an agent. Offer to write it into the project's `scripts/` or `.swiss-cheese/scripts/`.

## 3. Implement together

- **scripted**: write the script/command with the user, run it against the current repo, tune false positives *now* (a noisy layer gets disabled within a week). Add to config: `{"id": "<id>", "type": "scripted", "command": "...", "fast": true, "holes": "..."}`. Offer to add it to CI and pre-commit too — the same check in more slices.
- **hook**: add the extension→command mapping to the `agent-hooks` layer's `on_edit`. Command gets `{file}` substituted; non-zero exit + stderr = feedback to the agent.
- **agents**: create `.claude/agents/review-<id>.md` in the project, modeled on the plugin's review agents: frontmatter with `tools: Read, Grep, Glob`; body = one lens, the shared-diff input protocol ("Read diff.patch from the given path; open sources only to confirm"), the `FINDING: severity | file:line | issue | fix` output contract, and "stay in your lane". Then add the id to the review layer's `agents` list. Warn: each agent slice costs tokens per review — the lens must pay for itself.
- **knowledge/process**: write the doc/checklist item and reference it in the layer entry.

## 4. Name the holes

Ask: "what will this layer MISS?" and record it in the layer's `"holes"` field. If the user can't name a hole, they don't understand the layer yet — help them find one (every real layer has several). Check independence: does an existing layer share the same blind spot? If yes, note which neighbor covers it.

## 5. Test the layer

Prove it works before declaring done: introduce (or simulate in a scratch file) one defect of the named class and confirm the layer flags it; confirm a clean run stays quiet. For agent layers, run one review against a synthetic diff. Finish by running `layer_status.py` to show the updated stack.
