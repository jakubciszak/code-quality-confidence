# cr-learner

**RAG-based code-review assistant** that learns from your GitLab MR or GitHub PR history
and injects relevant lessons into [PR-Agent / Qodo Merge](https://github.com/Codium-ai/pr-agent)
as `extra_instructions`.

> **TL;DR**: Instead of fine-tuning a model, we build a vector store of
> "lessons" extracted from past PR/MR discussions using an LLM, then retrieve
> the most similar lessons for every new diff and feed them to an LLM
> reviewer.  This gives you 80% of the value for 20% of the effort.

---

## Supported platforms

| Platform | Mining | Webhook feedback |
|---|---|---|
| **GitLab** (self-hosted or gitlab.com) | ✅ | ✅ |
| **GitHub** (github.com or GitHub Enterprise) | ✅ | ✅ |

Both platforms produce the same internal data model so all downstream
components (store, integration, feedback loop) are fully platform-agnostic.

---

## Architecture

```
        ┌─────────────────────────┐   ┌─────────────────────────┐
        │   GitLab (MR history)   │   │  GitHub (PR history)    │
        └────────────┬────────────┘   └────────────┬────────────┘
                     │ REST API                    │ REST API
        ┌────────────┼────────────────────────────┤
        │            │                            │
        ▼            ▼                            ▼
┌──────────────┐  ┌──────────────┐      ┌──────────────┐
│   MINING     │  │  WEBHOOK     │      │  PR-AGENT    │
│ (offline /   │  │ (online,     │      │ (CI / hook)  │
│  CI cron)    │  │  feedback)   │      │              │
└──────┬───────┘  └──────┬───────┘      └──────▲───────┘
       │                 │                     │
       │  lessons+scores │                     │
       ▼                 ▼                     │
┌──────────────────────────────────────┐       │
│   PostgreSQL + pgvector              │       │
│   (Lessons Store)                    │──top-K►│
└──────────────────────────────────────┘       │
                                   extra_instructions
```

### Four components

| Module | Responsibility |
|---|---|
| `cr_learner.extractors` | Pull PR/MR data (diff, discussions, versions, approvals) from GitLab or GitHub REST API; use Claude to extract structured lessons |
| `cr_learner.store` | pgvector store with composite scoring: *authority × feedback-boost × (1−conflict) × time-decay* |
| `cr_learner.integration` | PR-Agent hook — embed diff, retrieve top-K lessons, format `extra_instructions` |
| `cr_learner.feedback` | FastAPI webhook — update lesson scores from GitLab and GitHub events |

---

## Six feedback signals

| Signal | Effect |
|---|---|
| `resolved` | Thread was marked resolved → +0.15 score |
| `code_changed_after` | Author pushed a new commit after the comment → +0.20 score |
| `award_count` | 👍 reactions on the comment → +0.02 per award (max +0.10) |
| `authority_score` | Reviewer is in the approvals list → 0.7; otherwise 0.5 |
| `negative_feedback` | Bot comment ignored / replied with "disagree" → −0.05 per hit |
| `conflict_penalty` | Senior A contradicts senior B → multiplied by (1−penalty) |

Score formula:

```
score = authority_score × feedback_boost × (1 − conflict_penalty) × exp(−λ × days)
```

Default `λ = 0.005` → half-life ≈ 139 days.

---

## Quick start

### 1. Prerequisites

- Python 3.11+
- Docker + Docker Compose (for the database)
- Anthropic API key (Claude + Voyage embeddings)
- GitLab **or** GitHub personal access token

### 2. Start the database

```bash
docker compose up db -d
```

### 3. Configure

```bash
cp .env.example .env
# Edit .env — set PLATFORM, your token, and ANTHROPIC_API_KEY
```

**GitLab:**
```env
PLATFORM=gitlab
GITLAB_TOKEN=glpat-...
GITLAB_PROJECT_ID=12345678
```

**GitHub:**
```env
PLATFORM=github
GITHUB_TOKEN=ghp_...
GITHUB_REPO=myorg/myrepo
```

### 4. Install

```bash
pip install -e ".[dev]"
```

### 5. Initialise schema

```bash
cr-learner init-db
```

### 6. Mine historical PRs/MRs

```bash
# Use platform from .env
cr-learner mine --limit 50

# Override platform on the fly
cr-learner mine --platform github --project-id myorg/myrepo --limit 50
cr-learner mine --platform gitlab --project-id 12345 --limit 50

# Process a single PR/MR
cr-learner mine --pr-number 123
```

### 7. Review a diff

```bash
git diff main..HEAD | cr-learner review --domain python
cr-learner review --diff-file my.diff --top-k 3
```

### 8. Start the feedback webhook

```bash
cr-learner serve
# or via Docker Compose:
docker compose up webhook -d
```

The single `/webhook` endpoint auto-detects the platform by inspecting
incoming headers:

| Header | Platform |
|---|---|
| `X-Gitlab-Event` | GitLab |
| `X-GitHub-Event` | GitHub |

**GitLab** — configure a project webhook pointing to `http://your-host:8080/webhook`
with these events:
- Emoji events
- Comments
- Merge request events

**GitHub** — configure a repository webhook pointing to `http://your-host:8080/webhook`
with these events:
- Pull request reviews
- Pull request review comments
- Issue comments
- Reactions (optional — for 👍 signals)

Set `WEBHOOK_SECRET` in `.env`. For GitLab it is compared as a plain token; for
GitHub it is used as the HMAC-SHA256 key (`X-Hub-Signature-256`).

---

## GitHub Actions integration

Add a workflow step to run `cr-learner review` on every pull request:

```yaml
# .github/workflows/cr-review.yml
name: AI Code Review

on:
  pull_request:
    types: [opened, synchronize]

jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install cr-learner
        run: pip install cr-learner   # or from source

      - name: Generate review context
        env:
          PLATFORM: github
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          GITHUB_REPO: ${{ github.repository }}
          DATABASE_URL: ${{ secrets.CR_DATABASE_URL }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: |
          git diff origin/${{ github.base_ref }}...HEAD > /tmp/pr.diff
          cr-learner review --diff-file /tmp/pr.diff --domain python > /tmp/extra_instructions.txt

      - name: Post review as PR comment
        uses: actions/github-script@v7
        with:
          script: |
            const fs = require('fs');
            const body = fs.readFileSync('/tmp/extra_instructions.txt', 'utf8');
            if (body.trim()) {
              github.rest.issues.createComment({
                issue_number: context.issue.number,
                owner: context.repo.owner,
                repo: context.repo.repo,
                body: body,
              });
            }
```

---

## PR-Agent integration

In your `pr_agent` configuration (`.pr_agent.toml` or environment variables):

```toml
[pr_reviewer]
extra_instructions = """
<PASTE OUTPUT OF: cr-learner review --diff-file $DIFF_FILE>
"""
```

For full automation, call `cr-learner review` inside the PR-Agent CI step and
inject its output into `extra_instructions` before running `/review`.

---

## Running tests

```bash
pytest tests/ -v
```

---

## Configuration reference

All settings are loaded from the `.env` file (see `.env.example`).

| Variable | Default | Description |
|---|---|---|
| `PLATFORM` | `gitlab` | Active platform: `gitlab` or `github` |
| `GITLAB_URL` | `https://gitlab.com` | GitLab instance URL |
| `GITLAB_TOKEN` | — | GitLab personal access token |
| `GITLAB_PROJECT_ID` | — | Default GitLab project to mine |
| `GITHUB_URL` | `https://api.github.com` | GitHub API URL (change for GHE) |
| `GITHUB_TOKEN` | — | GitHub personal access token |
| `GITHUB_REPO` | — | Default GitHub repo (`owner/repo`) |
| `DATABASE_URL` | `postgresql://...` | pgvector-enabled Postgres DSN |
| `ANTHROPIC_API_KEY` | — | Anthropic API key |
| `EMBEDDING_PROVIDER` | `anthropic` | `anthropic` or `local` |
| `EMBEDDING_MODEL` | `voyage-code-2` | Voyage model name |
| `EMBEDDING_DIM` | `1536` | Vector dimension (must match model) |
| `RETRIEVAL_TOP_K` | `5` | Number of lessons retrieved per review |
| `TIME_DECAY_LAMBDA` | `0.005` | Per-day decay rate (half-life ≈ 139 days) |
| `AUTHORITY_WEIGHTS` | `{}` | JSON dict of domain → authority weight |
| `WEBHOOK_SECRET` | — | Shared secret (plain token for GitLab; HMAC key for GitHub) |
| `LLM_MODEL` | `claude-3-5-sonnet-20241022` | Claude model for lesson extraction |

---

## Recommended next steps

1. **Run `mine` on 20–30 PRs** and manually inspect the extracted lessons to
   calibrate quality before going wider.
2. **Add domain hints** via `AUTHORITY_WEIGHTS` for domains where certain
   reviewers carry more weight (e.g. `{"kafka": 0.9, "postgresql": 0.8}`).
3. **Set up the feedback webhook** so lesson scores improve automatically over
   time.
4. **Consider CodeRabbit / Qodo Merge** — if they cover 70% of needs out of
   the box, this custom RAG layer can still complement them by injecting
   org-specific lessons as `extra_instructions`.
