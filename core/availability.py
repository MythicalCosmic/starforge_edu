"""App-level availability + graceful degradation (fault isolation).

Every feature app can be turned OFF at runtime, and a down app never takes the whole API
with it:

* A **disabled** app's endpoints answer a clean ``503 service_unavailable`` JSON — never a
  crash — so every OTHER app keeps serving normally.
* Apps declare their dependencies. A **hard** dependency being down makes the app
  ``unavailable`` (503, naming what's down). A **soft** dependency being down leaves the app
  ``up`` but **degraded** — it still works, and its JSON response carries a ``warnings`` list
  naming the degraded dependency (so a caller knows e.g. notifications aren't being sent).

Toggling is CONTROLLABLE without a restart: the disabled set is the union of the
``DISABLED_APPS`` setting (ops default) and a cache-backed override a director can change via
the system-status endpoint. Resolution is a cheap in-memory graph walk + one cache read, so
it adds negligible latency.

This module is pure logic (no Django models); the ``AppAvailabilityMiddleware`` and the
``/api/v1/org/system/`` endpoints drive it.
"""

from __future__ import annotations

from django.conf import settings
from django.core.cache import cache

# URL mount (/api/v1/<mount>/) -> app label. Most mounts equal the label; the exceptions
# are listed explicitly. Anything not here is treated as an unmanaged path (always up).
APP_MOUNTS: dict[str, str] = {
    "auth": "auth", "users": "users", "org": "org", "students": "students",
    "parents": "parents", "teachers": "teachers", "cohorts": "cohorts",
    "schedule": "schedule", "attendance": "attendance", "academics": "academics",
    "assignments": "assignments", "content": "content", "printing": "printing",
    "finance": "finance", "payments": "payments", "notifications": "notifications",
    "ai": "ai", "audit": "audit", "reports": "reports", "approvals": "approvals",
    "rulebook": "compliance", "access": "access", "forms": "forms", "tasks": "staff_tasks",
    "messaging": "messaging", "intelligence": "intelligence", "achievements": "achievements",
    "rewards": "rewards", "cover": "covers", "loans": "loans", "procurement": "procurement",
    "campaigns": "campaigns", "sales": "sales", "meetings": "meetings",
    "placement": "placement", "cards": "cards",
}

# The dependency graph. HARD = the app cannot function without it (down -> 503). SOFT = the
# app degrades but keeps working (down -> a warning on the response). Deliberately
# CONSERVATIVE: only architecturally-required edges are HARD (a wrong hard edge would 503 a
# still-usable app); everything else is SOFT so the default is "keeps working". Foundational
# apps (auth/users/org/tenancy/approvals/audit/access) have no deps — they ARE the base and
# should not normally be disabled. Extend freely; a missing app defaults to no deps.
APP_DEPENDENCIES: dict[str, dict[str, list[str]]] = {
    # money spine — the A-1 approvals/ledger engine is a hard requirement
    "finance": {"hard": ["approvals"], "soft": ["notifications"]},
    "payments": {"hard": ["finance", "approvals"], "soft": ["notifications"]},
    "loans": {"hard": ["approvals"], "soft": []},
    "sales": {"hard": ["approvals"], "soft": []},
    "procurement": {"hard": ["approvals"], "soft": []},
    "rewards": {"hard": ["approvals"], "soft": []},
    # attendance is keyed to schedule.Lesson + cohort membership
    "attendance": {"hard": ["schedule", "cohorts"], "soft": ["notifications", "cards"]},
    "covers": {"hard": ["schedule"], "soft": []},
    "assignments": {"hard": ["cohorts"], "soft": ["notifications"]},
    "academics": {"hard": ["cohorts"], "soft": []},
    "content": {"hard": ["cohorts"], "soft": []},
    "schedule": {"hard": ["cohorts"], "soft": ["notifications"]},
    # teacher payroll rides the A-1 engine, but the rest of teachers works without it
    "teachers": {"hard": [], "soft": ["approvals"]},
    "cards": {"hard": [], "soft": ["attendance"]},
    "parents": {"hard": ["students"], "soft": []},
    # AI-backed features degrade to manual when ai is off
    "placement": {"hard": [], "soft": ["ai"]},
    "campaigns": {"hard": [], "soft": ["ai", "notifications"]},
    "forms": {"hard": [], "soft": ["ai"]},
    # read-only aggregations degrade rather than fail
    "reports": {"hard": [], "soft": ["finance", "attendance", "academics"]},
    "intelligence": {"hard": [], "soft": ["finance", "attendance", "academics"]},
    "messaging": {"hard": [], "soft": ["notifications"]},
}

_DISABLED_CACHE_PREFIX = "core:availability:disabled_apps"

STATUS_UP = "up"
STATUS_DEGRADED = "degraded"
STATUS_DISABLED = "disabled"
STATUS_UNAVAILABLE = "unavailable"


def _global_disabled() -> frozenset[str]:
    """Ops-level disables (the DISABLED_APPS setting) — apply to EVERY tenant and can't be
    re-enabled per-tenant (a broken app is off everywhere)."""
    return frozenset(getattr(settings, "DISABLED_APPS", ()) or ())


def _cache_key() -> str:
    from core.utils import current_schema

    return f"{_DISABLED_CACHE_PREFIX}:{current_schema()}"


def disabled_apps() -> set[str]:
    """The apps off for the CURRENT tenant: the global ops default UNION this tenant's
    runtime override (a director toggling apps, no restart needed)."""
    override = cache.get(_cache_key()) or ()
    return set(_global_disabled()) | set(override)


def set_tenant_disabled_apps(apps: set[str]) -> set[str]:
    """Persist THIS tenant's disabled set (runtime toggle). Only known app labels are kept
    (a typo can't silently disable everything), and a globally-disabled app is implicitly
    included. Returns the resulting effective disabled set."""
    known = set(APP_MOUNTS.values())
    tenant_set = sorted(set(apps) & known)
    cache.set(_cache_key(), tenant_set, timeout=None)
    return set(tenant_set) | set(_global_disabled())


def app_for_mount(mount: str) -> str | None:
    """The app label a URL mount belongs to (None if the mount is unmanaged)."""
    return APP_MOUNTS.get(mount)


def resolve_status(app: str, _seen: frozenset[str] = frozenset()) -> tuple[str, list[str]]:
    """(status, warnings) for ``app``. Transitive: an app whose HARD dep resolves to
    disabled/unavailable is itself ``unavailable``; a SOFT dep that is disabled/unavailable
    downgrades it to ``degraded`` with a warning. Cycle-safe via ``_seen``."""
    disabled = disabled_apps()
    if app in disabled:
        return STATUS_DISABLED, [f"The {app} service is turned off."]
    if app in _seen:  # a dependency cycle — treat as up to avoid infinite recursion
        return STATUS_UP, []
    seen = _seen | {app}
    deps = APP_DEPENDENCIES.get(app, {})
    warnings: list[str] = []
    for hard in deps.get("hard", []):
        h_status, _ = resolve_status(hard, seen)
        if h_status in (STATUS_DISABLED, STATUS_UNAVAILABLE):
            return STATUS_UNAVAILABLE, [f"The {app} service is unavailable: it requires {hard}, which is down."]
    for soft in deps.get("soft", []):
        s_status, _ = resolve_status(soft, seen)
        if s_status in (STATUS_DISABLED, STATUS_UNAVAILABLE):
            warnings.append(f"{soft} is down — {app} is running in a degraded mode.")
    return (STATUS_DEGRADED if warnings else STATUS_UP), warnings


def system_status() -> list[dict]:
    """A snapshot of every managed app's status — for the system-status endpoint."""
    out = []
    for app in sorted(set(APP_MOUNTS.values())):
        status, warnings = resolve_status(app)
        out.append({"app": app, "status": status, "warnings": warnings})
    return out
