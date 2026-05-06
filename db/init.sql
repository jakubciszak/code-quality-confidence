-- cr-learner database initialisation
-- Run once when setting up a new database.
-- The Python LessonStore.init_schema() method executes equivalent DDL
-- automatically; this file is provided for manual / migration tooling.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS lessons (
    id                   UUID PRIMARY KEY,
    project_id           TEXT NOT NULL,
    source_mr_iid        INTEGER NOT NULL,
    source_discussion_id TEXT NOT NULL,
    domain               TEXT NOT NULL DEFAULT 'general',
    problematic_code     TEXT NOT NULL DEFAULT '',
    reviewer_comment     TEXT NOT NULL DEFAULT '',
    author_fix           TEXT NOT NULL DEFAULT '',
    rule_text            TEXT NOT NULL,
    score                FLOAT NOT NULL DEFAULT 0.5,
    resolved             BOOLEAN NOT NULL DEFAULT FALSE,
    code_changed_after   BOOLEAN NOT NULL DEFAULT FALSE,
    award_count          INTEGER NOT NULL DEFAULT 0,
    authority_score      FLOAT NOT NULL DEFAULT 0.5,
    negative_feedback    INTEGER NOT NULL DEFAULT 0,
    conflict_penalty     FLOAT NOT NULL DEFAULT 0.0,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    embedding            vector(1536)
);

CREATE INDEX IF NOT EXISTS lessons_embedding_idx
    ON lessons USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

CREATE INDEX IF NOT EXISTS lessons_project_idx ON lessons (project_id);
CREATE INDEX IF NOT EXISTS lessons_domain_idx  ON lessons (domain);
