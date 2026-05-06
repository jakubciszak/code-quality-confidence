# cr-learner

**RAG-based code-review assistant** that learns from your GitLab MR history
and injects relevant lessons into [PR-Agent / Qodo Merge](https://github.com/Codium-ai/pr-agent)
as `extra_instructions`.

> **TL;DR**: Instead of fine-tuning a model, we build a vector store of
> "lessons" extracted from past MR discussions using an LLM, then retrieve
> the most similar lessons for every new MR diff and feed them to an LLM
> reviewer.  This gives you 80% of the value for 20% of the effort.

---

## Architecture

```
                   ┌──────────────────────────┐
                   │   GitLab (self-hosted)   │
                   │   gitlab.yourcompany.pl  │
                   └────────────┬─────────────┘
                                │ REST API
        ┌───────────────────────┼───────────────────────┐
        │                       │                       │
        ▼                       ▼                       ▼
┌──────────────┐      ┌──────────────┐        ┌──────────────┐
│   MINING     │      │  WEBHOOK     │        │  PR-AGENT    │
│ (offline,    │      │ (online,     │        │ (CI / hook)  │
│  cron)       │      │  feedback)   │        │              │
└──────┬───────┘      └──────┬───────┘        └──────▲───────┘
       │                     │                       │
       │   lessons + scores  │                       │
       ▼                     ▼                       │
┌──────────────────────────────────────┐             │
│   PostgreSQL + pgvector              │             │
│   (Lessons Store)                    │──retrieval─►│
└──────────────────────────────────────┘   top-K     │
                                                     │
                                       extra_instructions
                                       with factual lessons
```

### Four components

| Module | Responsibility |
|---|---|
| `cr_learner.extractors` | Pull MR data (diff, discussions, versions, approvals) from GitLab REST API; use Claude to extract structured lessons |
| `cr_learner.store` | pgvector store with composite scoring: *authority × feedback-boost × (1−conflict) × time-decay* |
| `cr_learner.integration` | PR-Agent hook — embed diff, retrieve top-K lessons, format `extra_instructions` |
| `cr_learner.feedback` | FastAPI webhook — update lesson scores from GitLab emoji/note/MR events |

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
- GitLab personal access token with `api` scope

### 2. Start the database

```bash
docker compose up db -d
```

### 3. Configure

```bash
cp .env.example .env
# Edit .env with your GITLAB_TOKEN, ANTHROPIC_API_KEY, etc.
```

### 4. Install

```bash
pip install -e ".[dev]"
```

### 5. Initialise schema

```bash
cr-learner init-db
```

### 6. Mine historical MRs

```bash
# Process the 50 most recently merged MRs
cr-learner mine --limit 50

# Or a specific MR
cr-learner mine --mr-iid 123
```

### 7. Review a diff

```bash
# Pipe a diff from git
git diff main..HEAD | cr-learner review --domain python

# Or from a file
cr-learner review --diff-file my.diff --top-k 3
```

### 8. Start the feedback webhook

```bash
cr-learner serve
# or via Docker Compose:
docker compose up webhook -d
```

Configure a GitLab project webhook to point to `http://your-host:8080/webhook`
with the following events checked:
- **Emoji events** (award/unaward on notes)
- **Comments** (note events)
- **Merge request events**

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
| `GITLAB_URL` | `https://gitlab.com` | GitLab instance URL |
| `GITLAB_TOKEN` | — | Personal access token |
| `GITLAB_PROJECT_ID` | — | Default project to mine |
| `DATABASE_URL` | `postgresql://...` | pgvector-enabled Postgres DSN |
| `ANTHROPIC_API_KEY` | — | Anthropic API key |
| `EMBEDDING_PROVIDER` | `anthropic` | `anthropic` or `local` |
| `EMBEDDING_MODEL` | `voyage-code-2` | Voyage model name |
| `EMBEDDING_DIM` | `1536` | Vector dimension (must match model) |
| `RETRIEVAL_TOP_K` | `5` | Number of lessons retrieved per review |
| `TIME_DECAY_LAMBDA` | `0.005` | Per-day decay rate (half-life ≈ 139 days) |
| `AUTHORITY_WEIGHTS` | `{}` | JSON dict of domain → authority weight |
| `WEBHOOK_SECRET` | — | GitLab webhook token |
| `LLM_MODEL` | `claude-3-5-sonnet-20241022` | Claude model for lesson extraction |

---

## Recommended next steps

1. **Run `mine` on 20–30 MRs** and manually inspect the extracted lessons to
   calibrate quality before going wider.
2. **Add domain hints** via `AUTHORITY_WEIGHTS` for domains where certain
   reviewers carry more weight (e.g. `{"kafka": 0.9, "postgresql": 0.8}`).
3. **Set up the feedback webhook** so lesson scores improve automatically over
   time.
4. **Consider CodeRabbit / Qodo Merge** — if they cover 70% of needs out of
   the box, this custom RAG layer can still complement them by injecting
   org-specific lessons as `extra_instructions`.
