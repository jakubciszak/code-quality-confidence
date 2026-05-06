"""Command-line interface for cr-learner.

Commands
--------
mine        Fetch historical MRs from GitLab, extract lessons and store them.
review      Given a diff (file or stdin), print extra_instructions.
serve       Start the feedback webhook server.
init-db     Initialise the database schema.
"""
from __future__ import annotations

import sys

import click

from cr_learner.config import settings


@click.group()
def cli() -> None:
    """cr-learner — RAG-based code-review assistant."""


# ---------------------------------------------------------------------------
# init-db
# ---------------------------------------------------------------------------


@cli.command("init-db")
def init_db() -> None:
    """Initialise the PostgreSQL schema (idempotent)."""
    from cr_learner.store import LessonStore

    with LessonStore() as store:
        store.init_schema()
    click.echo("Database schema initialised.")


# ---------------------------------------------------------------------------
# mine
# ---------------------------------------------------------------------------


@cli.command()
@click.option("--project-id", default=None, help="GitLab project ID (overrides config).")
@click.option(
    "--limit",
    default=50,
    show_default=True,
    help="Number of recent merged MRs to process.",
)
@click.option(
    "--mr-iid",
    default=None,
    type=int,
    help="Process a single MR by IID (ignores --limit).",
)
def mine(project_id: str | None, limit: int, mr_iid: int | None) -> None:
    """Extract lessons from historical GitLab MRs and store them."""
    from cr_learner.extractors import LessonExtractor, MRExtractor
    from cr_learner.store import LessonStore

    pid = project_id or settings.gitlab_project_id
    extractor = MRExtractor(pid)
    lesson_extractor = LessonExtractor()

    if mr_iid is not None:
        iids = [mr_iid]
    else:
        click.echo(f"Fetching up to {limit} merged MRs from project {pid} …")
        iids = extractor.list_merged_mr_iids(limit)
        click.echo(f"Found {len(iids)} MRs.")

    total_lessons = 0
    with LessonStore() as store:
        store.init_schema()
        for iid in iids:
            click.echo(f"  Processing MR !{iid} …", nl=False)
            mr_data = extractor.extract(iid)
            lessons_for_mr = 0
            for discussion in mr_data.discussions:
                if not discussion.resolvable and not discussion.resolved:
                    continue
                lesson = lesson_extractor.extract(mr_data, discussion)
                if lesson:
                    store.upsert(lesson)
                    lessons_for_mr += 1
            click.echo(f" {lessons_for_mr} lesson(s).")
            total_lessons += lessons_for_mr

    click.echo(f"\nDone. Stored {total_lessons} lesson(s) total.")


# ---------------------------------------------------------------------------
# review
# ---------------------------------------------------------------------------


@cli.command()
@click.option("--project-id", default=None, help="GitLab project ID.")
@click.option("--mr-iid", default=0, type=int, help="MR IID (informational).")
@click.option("--domain", default="general", show_default=True, help="Domain hint.")
@click.option(
    "--diff-file",
    default=None,
    type=click.Path(exists=True),
    help="Path to diff file. Reads stdin if omitted.",
)
@click.option(
    "--top-k",
    default=None,
    type=int,
    help="Number of lessons to retrieve (overrides config).",
)
def review(
    project_id: str | None,
    mr_iid: int,
    domain: str,
    diff_file: str | None,
    top_k: int | None,
) -> None:
    """Print extra_instructions for a diff (file or stdin)."""
    from cr_learner.integration import build_review_context
    from cr_learner.models import ReviewContext
    from cr_learner.store import LessonStore

    if diff_file:
        with open(diff_file) as fh:
            diff = fh.read()
    else:
        if sys.stdin.isatty():
            click.echo("Reading diff from stdin (Ctrl-D to finish)…", err=True)
        diff = sys.stdin.read()

    if not diff.strip():
        click.echo("Empty diff — nothing to review.", err=True)
        raise SystemExit(1)

    ctx = ReviewContext(
        project_id=project_id or settings.gitlab_project_id,
        mr_iid=mr_iid,
        diff=diff,
        domain_hint=domain,
    )

    if top_k:
        settings.retrieval_top_k = top_k

    with LessonStore() as store:
        result = build_review_context(ctx, store)

    if result.extra_instructions:
        click.echo(result.extra_instructions)
    else:
        click.echo("No relevant lessons found for this diff.")


# ---------------------------------------------------------------------------
# serve
# ---------------------------------------------------------------------------


@cli.command()
@click.option("--host", default=None, help="Bind host (overrides config).")
@click.option("--port", default=None, type=int, help="Bind port (overrides config).")
def serve(host: str | None, port: int | None) -> None:
    """Start the GitLab feedback webhook server."""
    import uvicorn

    from cr_learner.feedback import app as feedback_app

    uvicorn.run(
        feedback_app,
        host=host or settings.webhook_host,
        port=port or settings.webhook_port,
    )


if __name__ == "__main__":
    cli()
