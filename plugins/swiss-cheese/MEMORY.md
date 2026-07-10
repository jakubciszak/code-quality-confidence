# Agent memory — index & protocol

This file is the **index** for the persistent memory the review lenses keep in
their `.claude/agent-memory/<agent>/` directories (committed to the repo — it's
shared team knowledge). Each lens links its topic files here:

```
- [Title](file.md) — <write-trigger that produced it>
```

Example (a real project accretes these over time):

```
- [Auth model](project_auth-model.md) — durable convention
- [Module map](arch_module-map.md) — durable convention
- [ADR digest](reference_adr-digest.md) — durable convention
- [Accepted N+1 in reporting](feedback_accepted-perf.md) — false-positive dismissed
- [Recurring null-handling bug](patterns_null-handling.md) — recurring pattern
```

## File-name prefixes (one consistent scheme)

| prefix       | holds                                                        |
|--------------|-------------------------------------------------------------|
| `feedback_`  | findings dismissed as false-positive / accepted-by-design   |
| `project_`   | durable project facts (auth mechanism, trust boundaries)    |
| `reference_` | digests of external truth (ADRs, specs) — id → decision      |
| `arch_`      | module/layer map, dependency rules                          |
| `patterns_`  | recurring bug/defect patterns seen in this repo             |

## Frontmatter — one key: `metadata.type`

Every memory file starts with frontmatter using the single unified key
`metadata.type` (never a second synonym like `kind`/`category`):

```yaml
---
metadata:
  type: project        # feedback | project | reference | arch | patterns
---
```

## Revalidation protocol — update, don't accrete sediment

Agents **revise their own prior findings** instead of stacking new entries.
Every updated entry begins with one of these markers and a reference:

- `**UPDATE (<ref>):**` — the entry changed; here's the new state.
- `**STALE:**` — the entry no longer holds; kept for provenance.
- `**RESOLVED:**` — the issue/decision is settled; no longer actionable.

## Hard write triggers — the ONLY reasons to write

Not "update memory" in general. An agent writes to memory **only** when:

1. a finding of its was **dismissed** as a false-positive (record so it stops re-flagging),
2. it discovered a **durable convention** (an invariant, a safe wrapper, a layer rule),
3. an existing entry proved **stale** (revise it with a marker above).

Outside these three triggers, agents write nothing — memory stays short and
load-bearing, not a diary.

## Relationship to the audit log

Memory is what the *lenses* carry forward. The **audit log**
(`.swiss-cheese/audit/YYYY-MM.jsonl`) is the *system's* record. In particular,
a review finding is only retired after a `finding_dismissed` audit entry
(fail-closed) — the same event that triggers a `feedback_` memory write.
