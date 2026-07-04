---
description: Add a predefined Swiss Cheese layer or build a custom one with guided hand-holding
argument-hint: "[add <layer-id> | custom | list]"
---

Manage the defense stack in `.swiss-cheese/config.json`. If the project is not initialized, offer to run `/swiss-cheese:init` instead (a single layer without a stack is exactly the single-point-of-failure the model warns about).

Parse `$ARGUMENTS`:

## `list` (or empty)

Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/layer_status.py"` and show the stack plus missing catalog layers. Ask whether to add one (predefined) or build a custom layer.

## `add <layer-id>`

Look the layer up in the catalog (`layer-catalog.md` in the `swiss-cheese-model` skill). Derive concrete configuration from the repo (probe with `repo_probe.py` if needed), verify any command runs, append the layer to `config.json`, create supporting artifacts (e.g. pre-commit config, ADR dir) and show the updated status.

## `custom`

Guide the user **by the hand** through creating a custom layer. Load the `custom-layer` skill for the full methodology. In short:

1. **Define the failure mode**: ask what class of defect or risk this layer must catch, and where current layers let it through (which holes align today). A layer without a named failure mode is decoration.
2. **Pick the mechanism** — cheapest that works, in this order:
   - `scripted` (a deterministic command — zero tokens at runtime; if it can be a Python/shell script, it must be),
   - `hook` (per-edit check via the agent-hooks layer),
   - `agents` (an LLM judgment lens — only when the check genuinely needs judgment),
   - `knowledge`/`process` (docs, checklists, conventions).
3. **Build it with them**: for `scripted` write and test the script/command together; for `agents` write the agent file into the project's `.claude/agents/<name>.md` (focused system prompt, read-only tools, compact output format mirroring the plugin's review agents) and wire it into the review layer's agent list; for `hook` extend `on_edit` in config.
4. **Name the holes**: ask "what will this layer MISS?" and record the answer in the layer's `"holes"` field in config — every slice has holes; unnamed holes are the dangerous ones.
5. **Test the layer** on a real or synthetic defect before declaring it done, then show the updated stack via `layer_status.py`.
