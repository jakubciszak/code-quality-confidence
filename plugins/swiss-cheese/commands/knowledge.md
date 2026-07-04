---
description: Wire up where task knowledge lives (Jira, Redmine, Linear, GitHub Issues…) and discover MCP servers/skills for it
argument-hint: "[tracker name, e.g. jira]"
---

Configure the **knowledge sources** the Swiss Cheese loop uses to understand tasks (`/swiss-cheese:loop` pulls work from here).

## 1. Ask where tasks live

If `$ARGUMENTS` doesn't name a tracker, use AskUserQuestion: Jira / Redmine / Linear / GitHub Issues / Azure DevOps / Trello / other / "docs in repo only". Also ask where *domain* knowledge lives if relevant (Confluence, Notion, Google Drive, wiki in repo).

## 2. Discover integrations — search, don't guess

For each chosen source, find a real integration in this order:

1. **Already connected?** Check available tools for an existing MCP server (e.g. `mcp__jira__*`, `mcp__github__*`) — if present, just record it.
2. **Registry/plugin search** — if tools like SearchMcpRegistry, SearchPlugins, SearchSkills or ListConnectors are available in this session, use them with the tracker name.
3. **Web search fallback** — search for `<tracker> MCP server` (official vendors first: Atlassian for Jira/Confluence, etc.). Prefer official/well-maintained servers; report the install command (`claude mcp add …`) rather than inventing config.

Present what you found with a one-line trust note (official / community / stars) and let the user pick.

## 3. Record and wire

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

Also append a short "Task knowledge" note to the CLAUDE.md Swiss Cheese section so future sessions know where to look. If an MCP server needs installation/authentication, give the exact commands and stop — never store credentials in any file.
