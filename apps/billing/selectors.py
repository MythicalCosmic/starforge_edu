"""Billing read-side selectors (PUBLIC schema).

All reads here run on the public schema (Plan/Subscription/UsageSnapshot live
only there). The middleware's per-request subscription lookup is cached for 60s
in Redis to avoid a public-schema query on every tenant request.
"""

from __future__ import annotations

from django.core.cache import cache
from django.db.models import QuerySet
from django_tenants.utils import get_public_schema_name, schema_context

from apps.billing.models import Plan, Subscription, UsageSnapshot

SUBSCRIPTION_CACHE_TIMEOUT = 60  # seconds (D3-E-4: avoid a public-schema query per request)


def subscription_cache_key(schema_name: str) -> str:
    return f"billing:subscription_status:{schema_name}"


def get_subscription_status(*, schema_name: str, center_id: int) -> str | None:
    """Cached subscription status for the tenant identified by `schema_name`.

    Returns the status string, or ``None`` if the Center has no subscription
    row yet (treated as pass-through by the gate — provisioning auto-creates one).
    The cache is invalidated by `services._invalidate_subscription_cache` on any
    status write.

    Billing tables live ONLY in the public schema (apps.billing is in
    SHARED_APPS). This is called from the gate middleware while the TENANT
    schema is active, so the query MUST run inside a public schema_context —
    otherwise Postgres' search_path has no billing_subscription relation. On a
    cache hit (the common path) no query runs and the context switch is skipped.
    """
    key = subscription_cache_key(schema_name)
    cached = cache.get(key)
    if cached is not None:
        # Sentinel "" means "no subscription row" (distinct from a cache miss).
        return cached or None
    with schema_context(get_public_schema_name()):
        status = Subscription.objects.filter(center_id=center_id).values_list("status", flat=True).first()
    cache.set(key, status or "", timeout=SUBSCRIPTION_CACHE_TIMEOUT)
    return status


def active_plans() -> QuerySet[Plan]:
    return Plan.objects.filter(is_active=True)


def subscription_for_center(*, center_id: int) -> Subscription | None:
    return Subscription.objects.select_related("plan", "center").filter(center_id=center_id).first()


def usage_for_center(*, center_id: int) -> QuerySet[UsageSnapshot]:
    return UsageSnapshot.objects.filter(center_id=center_id).select_related("center")
