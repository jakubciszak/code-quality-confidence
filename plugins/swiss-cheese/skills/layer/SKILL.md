---
name: layer
description: Add a predefined Swiss Cheese layer or build a custom one (failure mode → cheapest mechanism → named holes → test). Also lists the current stack. Invoke to manage defense layers.
disable-model-invocation: true
---

# Manage the defense stack

Edit `.swiss-cheese/config.json` (schema v2, `layers` keyed by id with `mode`). If the project isn't initialized, offer `/swiss-cheese:init` first — a single layer without a stack is the single point of failure the model warns against.

Parse `$ARGUMENTS`:

## `list` (or empty)

Show the stack and which catalog layers are missing (the aligned-holes risk). The full catalog with **named holes** per layer is in `references/layer-catalog.md`. Ask whether to add a predefined layer or build a custom one.

## `add <layer-id>`

Look the layer up in `references/layer-catalog.md`. Derive its concrete command with `runner_detector.py` (not `--version` guessing), set `mode` per risk profile, append it to `config.json`, create any supporting artifact, and show the updated stack.

## `custom`

Guide the user **by the hand** (load the `custom-layer` skill for the full method):

1. **Failure mode** — what class of defect must this catch, and which holes align today to let it through? A layer without a named failure mode is decoration.
2. **Cheapest mechanism that works**, in order: `scripted` (deterministic, zero runtime tokens — if it can be a script, it must be) → `hook` (per-edit) → `guards` (a new deterministic guard in `scripts/guards/`) → `agents` (LLM judgment, only when judgment is genuinely required) → `knowledge`/`process`.
3. **Build it together** — for scripted, write and test the command; for a guard, add a `scripts/guards/<name>.py` with `scan(ctx)`; for an agent, a read-only lens with the five-field finding format including `verification`.
4. **Name the holes** — "what will this MISS?" → record in the layer's `holes` field. Unnamed holes are the dangerous ones.
5. **Test on a real/synthetic defect** before declaring done, then show the updated stack.
