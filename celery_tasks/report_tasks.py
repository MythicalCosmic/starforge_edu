"""Celery tasks for report generation + scheduled exports."""

from __future__ import annotations

from config.celery import app


@app.task(bind=True)
def build_report(self, report_id: int) -> None:
    # TODO(v1): apps.reports.services.build(report_id)
    return None
