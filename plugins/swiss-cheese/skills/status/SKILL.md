---
name: status
description: Show the Swiss Cheese defense stack, its named holes, and the last gate results. Invoke to see which layers are active and which are missing.
disable-model-invocation: true
---

# Defense stack status

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/layer_status.py"
```

Display its markdown verbatim. If `.swiss-cheese/runs/latest/guards.json` exists, add one line summarizing the last run (guard findings, escalate). Then, if an obvious catalog layer is missing, one short recommendation — no repo exploration, no extra commentary.
