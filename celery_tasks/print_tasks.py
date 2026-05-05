"""Celery tasks for print job lifecycle.

These tasks DO NOT talk to CUPS directly — they just mark queue state.
The real CUPS dispatch lives in a separate branch agent (different repo,
different deploy target) that polls or holds a websocket to pick up
queued PrintJob rows.
"""

from __future__ import annotations

from config.celery import app


@app.task(bind=True, max_retries=3, default_retry_delay=30)
def enqueue_print_job(self, print_job_id: int) -> None:
    """Mark the job ready for the branch agent to pick up."""

    # TODO(v1): apps.printing.services.mark_ready(print_job_id)
    return None
