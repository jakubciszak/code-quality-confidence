# Injection & prompt-control patterns (guard reference)

The `injection` guard scans **added diff lines** for these patterns. This file
is the human-readable catalog; the machine-readable list lives in
`references/injection-patterns.json` (loaded by the guard, with an embedded
fallback so the guard still runs if the file is missing).

A diff is **data, never instructions** — the guard flags attempts to smuggle
instructions to the agent through code, comments, or fixtures. It never
executes the diff.

## Hard prompt-injection → `blocker`

Literal control tokens and instruction-override phrasings that only make sense
as an attack on the reviewing/coding agent:

- `ignore previous instructions` (and close variants)
- `<|im_start|>` — chat-template control token
- `[/INST]` — Llama instruction delimiter
- `<<SYS>>` — system-prompt delimiter
- `export ANTHROPIC_API_KEY` — key exfiltration setup

## Soft "comment & control" → `medium`

Phrases that try to talk a reviewer/agent out of doing its job. Individually
weak (they appear in honest code too), so they warn rather than block:

- `// ai: approve`, `# ai: approve`
- `trust me`
- `this is safe because`
- `don't review` / `do not review`

## Agent-control file modification → `high`

Editing the files that steer the agent is high-signal: a poisoned rule file
compromises every later layer. Matched on **changed path**, not content:

- `.claude/**`
- `CLAUDE.md`, `AGENTS.md`
- `.cursorrules`
- `*mcp.json`

## Named holes

- Regex-based: a new phrasing of "ignore your instructions" that avoids these
  literals slips through. Soft list is intentionally small to avoid noise.
- Content in binary/minified blobs is not scanned line-by-line.
