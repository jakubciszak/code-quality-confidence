## Swiss Cheese layers

This repository uses the Swiss Cheese model of layered defense (plugin: `swiss-cheese`). No single check is trusted; every change must pass the stack. Configuration: `.swiss-cheese/config.json`.

**Gates every change must pass (in order):**

{LAYER_LIST — e.g.:
1. `lint` — `ruff check .` (fix, never suppress without a comment saying why)
2. `typecheck` — `mypy src`
3. `tests` — `pytest -q` (never weaken or skip a test to make it pass — report instead)
4. `review` — run `/swiss-cheese:review` before committing; fix blocker/high findings}

**Rules for agent sessions:**

- After completing a change, run the gates: `python3 <plugin>/scripts/check_layers.py --fast`, then full, then `/swiss-cheese:review`.
- Never disable, weaken, or bypass a layer to get green. If a layer seems wrong, finish and report it.
- Architectural decisions go to `{ADR_DIR}` (template: `docs/adr/0001-…`). If your change makes a decision implicitly, record it.
- Task knowledge sources: {KNOWLEDGE_SOURCES or "see .swiss-cheese/knowledge.json"}.
