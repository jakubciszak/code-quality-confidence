---
description: Show the Swiss Cheese defense stack, its holes, and last gate results
---

Run:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/layer_status.py"
```

Display its markdown output verbatim. Then, if `.swiss-cheese/runs/latest/manifest.json` exists, add one line summarizing the last review run (files, agents run/skipped). Do not explore the repository or add commentary beyond one short recommendation if an obvious gap exists.
