---
description: Audit documentation, ADRs and code-review practice — the knowledge layers of the Swiss Cheese stack
---

Audit the *knowledge layers* of this repository: documentation, architecture decision records, and review practice. These layers catch the defects automation can't — missing context.

## 1. Probe

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/repo_probe.py" .
```

Then Read only what the probe found (README, CONTRIBUTING, ADR files — skim, don't quote at length).

## 2. Assess each knowledge layer

**README** — can a new contributor build, test and run the project from it alone? Grade: missing / stub / adequate / good.

**Onboarding & conventions** — CONTRIBUTING.md, ARCHITECTURE.md, CLAUDE.md. Does an agent session know the project's rules without asking?

**ADRs** — do they exist? Are they current (compare newest ADR date vs. recent commit activity from the probe)? If absent: pick 2–3 *actual* architectural decisions visible in the codebase (framework choice, module layout, persistence strategy) and propose them as the first ADRs — concrete titles, not generic advice.

**Code review practice** — PR template, CODEOWNERS, `docs/review-checklist.md`, review style in `.swiss-cheese/config.json`. Recommend a review style matched to the repo: solo project ⇒ agent review `blocking` replaces the human layer; team ⇒ checklist + severity-gated agent review before human review.

**Security docs** — SECURITY.md and secrets hygiene (is there a secrets-scan layer? `.env` in `.gitignore`?).

## 3. Report

A short table: layer · state · risk if missing · recommended action (one line each). Then the top 3 actions ranked by risk reduction per unit of effort. Offer to generate any missing artifact from the plugin templates (`adr-template.md`, `review-checklist.md`, `claude-md-section.md`) — generate only on confirmation.
