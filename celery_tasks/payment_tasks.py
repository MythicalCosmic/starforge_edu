"""Payments async tasks (D3-B-9, D3-B-10).

- ``fiscalize_payment`` — post-payment Soliq fiscalization. Idempotent (an
  existing CONFIRMED ``FiscalReceipt`` short-circuits in the service body),
  retries ≤3 with exponential backoff. Enqueued with ``_schema_name`` from the
  payment-completion chokepoint.
- ``generate_receipt_pdf`` — renders the fiscal receipt to PDF (weasyprint LAZY,
  in the service body) → S3 → the key is stored on the receipt payload so
  ``GET /payments/{id}/receipt/`` can sign it (TD-14). PDF render skips where the
  native lib is absent (test mirrors the academics transcript skip).

No weasyprint/Soliq call ever happens in a request handler (DoD #9).
"""

from __future__ import annotations

import requests

from config.celery import app


@app.task(
    bind=True,
    max_retries=3,
    autoretry_for=(requests.RequestException,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
)
def fiscalize_payment(self, payment_id: int) -> str | None:
    from apps.payments.services import fiscalize_payment_body, mark_fiscal_failed

    try:
        return fiscalize_payment_body(payment_id)
    except requests.RequestException:
        raise  # autoretry_for handles backoff/retry
    except Exception as exc:
        mark_fiscal_failed(payment_id, exc)
        raise self.retry(exc=exc) from exc


@app.task(bind=True, max_retries=3, retry_backoff=True)
def generate_receipt_pdf(self, payment_id: int) -> str | None:
    from apps.payments.services import generate_receipt_pdf_body

    try:
        return generate_receipt_pdf_body(payment_id)
    except Exception as exc:
        raise self.retry(exc=exc) from exc
