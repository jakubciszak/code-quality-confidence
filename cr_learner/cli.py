"""Command-line interface for cr-learner.

Commands
--------
mine        Fetch historical PRs/MRs, extract lessons and store them.
review      Given a diff (file or stdin), print extra_instructions.
serve       Start the feedback webhook server.
init-db     Initialise the database schema.
"""
from __future__ import annotations

import sys

import click

from cr_learner.config import settings

_PLATFORM_CHOICES = click.Choice(["gitlab", "github"], case_sensitive=False)


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
@click.option(
    "--platform",
    default=None,
    type=_PLATFORM_CHOICES,
    help="Source platform: 'gitlab' or 'github'. Overrides PLATFORM env var.",
)
@click.option(
    "--project-id",
    default=None,
    help=(
        "GitLab project ID  OR  GitHub 'owner/repo' slug. "
        "Overrides GITLAB_PROJECT_ID / GITHUB_REPO env vars."
    ),
)
@click.option(
    "--limit",
    default=50,
    show_default=True,
    help="Number of recent merged PRs/MRs to process.",
)
@click.option(
    "--pr-number",
    default=None,
    type=int,
    help="Process a single PR/MR by number (ignores --limit).",
)
def mine(
    platform: str | None,
    project_id: str | None,
    limit: int,
    pr_number: int | None,
) -> None:
    """Extract lessons from historical PRs/MRs and store them."""
    from cr_learner.extractors import LessonExtractor, get_extractor
    from cr_learner.store import LessonStore

    p = platform or settings.platform
    pid = project_id or settings.default_project_id

    extractor = get_extractor(platform=p, project_id=pid)
    lesson_extractor = LessonExtractor()

    if pr_number is not None:
        numbers = [pr_number]
    else:
        click.echo(f"Fetching up to {limit} merged PRs from {p}/{pid} …")
        numbers = extractor.list_merged_pr_numbers(limit)
        click.echo(f"Found {len(numbers)} PRs.")

    total_lessons = 0
    with LessonStore() as store:
        store.init_schema()
        for number in numbers:
            click.echo(f"  Processing PR #{number} …", nl=False)
            pr_data = extractor.extract(number)
            lessons_for_pr = 0
            for discussion in pr_data.discussions:
                if not discussion.resolvable and not discussion.resolved:
                    continue
                lesson = lesson_extractor.extract(pr_data, discussion)
                if lesson:
                    store.upsert(lesson)
                    lessons_for_pr += 1
            click.echo(f" {lessons_for_pr} lesson(s).")
            total_lessons += lessons_for_pr

    click.echo(f"\nDone. Stored {total_lessons} lesson(s) total.")


# ---------------------------------------------------------------------------
# review
# ---------------------------------------------------------------------------


@cli.command()
@click.option("--project-id", default=None, help="Project ID or 'owner/repo' slug.")
@click.option("--pr-number", default=0, type=int, help="PR/MR number (informational).")
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
    pr_number: int,
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
        project_id=project_id or settings.default_project_id,
        mr_iid=pr_number,
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
    """Start the feedback webhook server (supports GitLab and GitHub events)."""
    import uvicorn

    from cr_learner.feedback import app as feedback_app

    uvicorn.run(
        feedback_app,
        host=host or settings.webhook_host,
        port=port or settings.webhook_port,
    )


if __name__ == "__main__":
    cli()
