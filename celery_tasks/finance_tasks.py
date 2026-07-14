"""Finance beat/async tasks (D3-A-7, D3-A-8).

- `generate_statement_pdf` renders a statement-of-account to PDF (weasyprint,
  lazy import in the service) and uploads it to `{schema}/documents/` (TD-14),
  caching the task-id -> S3 key map so the result endpoint can sign it. Per-tenant
  (enqueued with `_schema_name`), retries <=3 with backoff. No weasyprint/S3 call
  ever happens in a request handler (DoD #9).
- `late_payment_reminders` is the daily beat task: it fans out per active Center,
  scans overdue invoices, and emits `payment_reminder` once per invoice per
  `CenterSettings.payment_reminder_interval_days` (dedupe in the service body).
- `refresh_fx_rates` (mock-first) caches the per-tenant CBU UZS->USD rate that
  `issue_invoice` snapshots; real CBU fetch flips on when the source is live.
"""

from __future__ import annotations

from config.celery import app


def _active_schemas() -> list[str]:
    from django_tenants.utils import get_public_schema_name

    from apps.tenancy.models import Center

    return list(
        Center.objects.filter(is_active=True)
        .exclude(schema_name=get_public_schema_name())
        .values_list("schema_name", flat=True)
    )


@app.task(bind=True, max_retries=3, retry_backoff=True)
def generate_statement_pdf(self, student_id: int, *, locale: str = "en") -> str | None:
    """Render + upload one student's statement; cache the task-id -> key map."""
    from django.core.cache import cache

    from apps.finance.services import generate_statement
    from core.utils import current_schema

    key = generate_statement(student_id, locale=locale)
    cache.set(
        f"finance:statement:{current_schema()}:{self.request.id}",
        key,
        timeout=3600,
    )
    return key


@app.task
def late_payment_reminders() -> int:
    """Daily public dispatcher; one failing center cannot starve later tenants."""
    schemas = _active_schemas()
    for schema in schemas:
        late_payment_reminders_for_schema.delay(_schema_name=schema)
    return len(schemas)


@app.task(bind=True, max_retries=3, retry_backoff=True)
def late_payment_reminders_for_schema(self) -> int:
    from apps.finance.services import emit_payment_reminders

    try:
        return emit_payment_reminders()
    except Exception as exc:
        raise self.retry(exc=exc) from exc


@app.task
def refresh_fx_rates() -> int:
    """Daily public dispatcher for tenant-local FX cache refreshes."""
    schemas = _active_schemas()
    for schema in schemas:
        refresh_fx_rate_for_schema.delay(_schema_name=schema)
    return len(schemas)


@app.task(bind=True, max_retries=3, retry_backoff=True)
def refresh_fx_rate_for_schema(self) -> str | None:
    """Cache the per-tenant CBU UZS->USD rate consumed by `issue_invoice`.

    Mock-first (TD-2): with `FINANCE_FX_USE_MOCK` True (default) this writes a
    deterministic placeholder rate so USD totals are populated in dev/tests. The
    real branch fetches the CBU JSON feed with `requests` (lazy import) when the
    flag is off and the source is "cbu". Per-tenant; fan out over active Centers.
    """

    from django.conf import settings
    from django.core.cache import cache

    from apps.org.selectors import get_center_settings
    from core.utils import current_schema

    try:
        cs = get_center_settings()
        if (cs.fx_source or "cbu") != "cbu":
            return None
        use_mock = getattr(settings, "FINANCE_FX_USE_MOCK", True)
        rate = _mock_cbu_rate() if use_mock else _live_cbu_rate()
        if rate is not None:
            cache.set(f"finance:fx_rate_usd:{current_schema()}", str(rate), timeout=24 * 3600)
        return str(rate) if rate is not None else None
    except Exception as exc:
        raise self.retry(exc=exc) from exc


def _mock_cbu_rate():
    from decimal import Decimal

    return Decimal("12500.0000")  # deterministic dev/test UZS per USD


def _live_cbu_rate():
    """Fetch the live CBU UZS->USD rate. `requests` is available; import lazily."""
    from decimal import Decimal

    import requests

    resp = requests.get("https://cbu.uz/uz/arkhiv-kursov-valyut/json/USD/", timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, list) and data:
        return Decimal(str(data[0]["Rate"]))
    return None
