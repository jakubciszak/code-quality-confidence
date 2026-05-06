"""PR-Agent integration hook.

Exposes a single public function :func:`build_review_context` that:
1. Takes a diff (and optional domain hint).
2. Embeds the diff.
3. Retrieves top-K similar lessons from the store.
4. Formats the lessons as ``extra_instructions`` text for PR-Agent.

PR-Agent calls this hook via its ``extra_instructions`` configuration key.
You can also call it directly for CLI usage.
"""
from __future__ import annotations

import logging

from cr_learner.config import settings
from cr_learner.models import ReviewContext, ReviewInstructions
from cr_learner.store import LessonStore

logger = logging.getLogger(__name__)


def build_review_context(
    context: ReviewContext,
    store: LessonStore | None = None,
) -> ReviewInstructions:
    """Return :class:`ReviewInstructions` for a given MR diff.

    Parameters
    ----------
    context:
        The :class:`ReviewContext` describing the current MR.
    store:
        An *already connected* :class:`LessonStore`.  If *None* a new store
        is created and connected for this call (useful for CLI / one-shot use).
    """
    own_store = store is None
    if own_store:
        store = LessonStore()
        store.connect()

    try:
        # Embed the diff
        query_embedding = store.embed_text(context.diff)

        # Retrieve top-K lessons
        lessons = store.search(
            query_embedding=query_embedding,
            top_k=settings.retrieval_top_k,
            domain=context.domain_hint if context.domain_hint != "general" else None,
        )

        if not lessons:
            logger.info(
                "No lessons found for MR !%s (project %s).",
                context.mr_iid,
                context.project_id,
            )
            return ReviewInstructions(lessons=[], extra_instructions="")

        instructions = ReviewInstructions.from_lessons(lessons)
        logger.info(
            "Retrieved %d lessons for MR !%s (project %s).",
            len(lessons),
            context.mr_iid,
            context.project_id,
        )
        return instructions
    finally:
        if own_store:
            store.close()
