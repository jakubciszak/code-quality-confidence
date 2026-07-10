---
name: intent
description: Reconstruct the intent of a task before any code is written — acceptance criteria, test plan, scope guards, risk, AI-disclosure block. Invoke consciously before starting a ticket.
disable-model-invocation: true
---

# Intent reconstruction (pre-code)

Turn a task/ticket into a crisp contract **before** implementation. You stop at the contract; you do **not** write code.

## 1. Get the ticket text (main session only)

If `.swiss-cheese/knowledge.json` names a task source reachable via MCP (Jira/Linear/etc.), fetch the ticket **here, in the main session** — a subagent cannot see MCP. Paste the ticket body into the context you pass onward. Otherwise use `$ARGUMENTS` / ask the user for the task.

## 2. Reconstruct the intent

Spawn the intent subagent (Haiku, read-only) with the Agent tool, `subagent_type = swiss-cheese:intent-agent`, passing the ticket text and letting it Grep/Read the repo to ground its answer. It returns — and you present — exactly:

1. **Reconstructed intent** — what outcome the task actually wants, in one paragraph.
2. **Acceptance criteria** — a checklist a reviewer could verify.
3. **Test plan** — the specific cases (happy path, edges, failure modes) that will prove it.
4. **Scope guards** — what is explicitly *out* of scope, to prevent creep.
5. **Risk classification** — `low | medium | high` with one sentence why (touches auth/payments/migrations ⇒ high), and whether it hits a `high_risk_paths` entry.
6. **AI-disclosure block** — a ready-to-paste block for the PR/commit body naming what was AI-assisted and how it was verified. This satisfies the `policy` guard's `AI-disclosure` check.

## 3. Stop

Present the contract and stop. Offer to proceed with `/swiss-cheese:loop` once the user confirms the intent is right. Writing code now would defeat the purpose — the point is to agree on the target before aiming.
