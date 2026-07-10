---
name: audit
description: Audit the knowledge layers — README, CONTRIBUTING, ADRs, review practice, security docs — and propose concrete fixes. Invoke to check the docs/process slices of the stack.
disable-model-invocation: true
---

# Audit the knowledge layers

Audit the layers automation can't cover: documentation, ADRs, review practice. These catch the defects that are about *missing context*.

## 1. Probe

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/repo_probe.py" .
```

Read only what the probe found (README, CONTRIBUTING, ADRs — skim).

## 2. Assess each knowledge layer

- **README** — can a newcomer build/test/run from it alone? missing / stub / adequate / good.
- **Onboarding & conventions** — CONTRIBUTING, ARCHITECTURE, CLAUDE.md: does an agent session know the rules without asking?
- **ADRs** — exist? current (newest ADR vs. recent commit activity)? If absent, propose 2–3 *actual* decisions visible in the code as the first ADRs (concrete titles).
- **Review practice** — PR template, CODEOWNERS, `docs/review-checklist.md`, `review` layer mode. Recommend a style matched to the repo (solo ⇒ agent review replaces human; team ⇒ checklist + gated review).
- **Security docs** — SECURITY.md, `.env` in `.gitignore`, a secrets-scan layer present?

## 3. Report

A short table: layer · state · risk if missing · one-line action. Then the top 3 actions by risk-reduction-per-effort. Offer to generate any missing artifact from `templates/` (only on confirmation).
