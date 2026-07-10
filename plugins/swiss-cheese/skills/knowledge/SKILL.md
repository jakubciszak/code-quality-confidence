---
name: knowledge
description: Wire up where task/domain knowledge lives (Jira, Linear, GitHub Issues, Confluence…) and discover MCP servers for it. Invoke to connect the loop to a task tracker.
disable-model-invocation: true
---

# Task-knowledge sources

Configure where `/swiss-cheese:loop` and `/swiss-cheese:intent` pull work from. Remember: **MCP is reachable only from the main session**, never from a plugin subagent — so the fetching skills read the ticket here and pass the text onward.

## 1. Ask where tasks live

If `$ARGUMENTS` doesn't name a tracker, use AskUserQuestion: Jira / Linear / GitHub Issues / Azure DevOps / Redmine / other / "docs in repo only". Also ask where domain knowledge lives if relevant (Confluence, Notion, wiki).

## 2. Discover integrations — search, don't guess

Per source, in order: (1) already-connected MCP tools (`mcp__jira__*`, `mcp__github__*`)? record it. (2) If SearchMcpRegistry / SearchPlugins / ListConnectors are available, search by tracker name. (3) Web-search fallback for `<tracker> MCP server` (official vendors first). Present each with a one-line trust note; let the user pick.

## 3. Record

Write `.swiss-cheese/knowledge.json`:

```json
{
  "task_sources": [
    {"kind": "jira", "via": "mcp", "server": "atlassian", "status": "connected|proposed",
     "usage": "fetch issue by key; list my open issues"}
  ],
  "domain_sources": [
    {"kind": "confluence", "via": "mcp", "server": "atlassian", "status": "proposed"}
  ]
}
```

Append a short "Task knowledge" note to the CLAUDE.md governance section. If a server needs install/auth, give the exact `claude mcp add …` command and stop — never store credentials anywhere.
