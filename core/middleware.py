"""Project middleware.

Three concerns, ordered in `config.settings.base.MIDDLEWARE`:

1. `RequestIDMiddleware` (outermost) — correlation id on every request/response.
2. `HealthCheckMiddleware` (before tenant resolution) — liveness/readiness probes
   that answer on any Host header without a tenant.
3. `InactiveTenantMiddleware` (after tenant resolution) — 503 on a deactivated
   Center (Lane B / D1-LB-6).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

from django.db import connection
from django.http import HttpRequest, HttpResponse, JsonResponse
from django_tenants.utils import get_public_schema_name

from core.logging_filters import request_id_var

REQUEST_ID_HEADER = "X-Request-ID"

GetResponse = Callable[[HttpRequest], HttpResponse]


class RequestIDMiddleware:
    """Honor an inbound ``X-Request-ID`` (verbatim) or mint a uuid4, expose it to
    the logging filters for the life of the request, and echo it on the response.
    """

    def __init__(self, get_response: GetResponse) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
        request.request_id = request_id  # type: ignore[attr-defined]
        token = request_id_var.set(request_id)
        try:
            response = self.get_response(request)
        finally:
            request_id_var.reset(token)
        response[REQUEST_ID_HEADER] = request_id
        return response


class HealthCheckMiddleware:
    """Ops probes that bypass tenant resolution, auth, and throttling.

    - ``GET /healthz/live``  → 200 always (the process is serving).
    - ``GET /healthz/ready`` → 200 when Postgres + Redis answer, else 503 with the
      TD-18 error envelope (``code="not_ready"``).
    """

    def __init__(self, get_response: GetResponse) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if request.path == "/healthz/live":
            return JsonResponse({"status": "ok"})
        if request.path == "/healthz/ready":
            return self._ready()
        return self.get_response(request)

    @staticmethod
    def _ready() -> HttpResponse:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
        except Exception:
            return JsonResponse(
                {"error": {"code": "not_ready", "detail": "Database unavailable."}},
                status=503,
            )
        try:
            from infrastructure.cache.redis_client import get_redis

            get_redis().ping()
        except Exception:
            return JsonResponse(
                {"error": {"code": "not_ready", "detail": "Cache unavailable."}},
                status=503,
            )
        return JsonResponse({"status": "ready"})


class InactiveTenantMiddleware:
    """Return 503 ``center_inactive`` for a resolved-but-inactive Center.

    Runs after ``TenantMainMiddleware`` so the tenant is resolved. The public
    schema is never blocked, and the health probes already short-circuited
    earlier in the chain.
    """

    def __init__(self, get_response: GetResponse) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        schema = getattr(connection, "schema_name", get_public_schema_name())
        if schema != get_public_schema_name():
            tenant = getattr(connection, "tenant", None)
            if tenant is not None and not getattr(tenant, "is_active", True):
                return JsonResponse(
                    {"error": {"code": "center_inactive", "detail": "This center is not active."}},
                    status=503,
                )
        return self.get_response(request)
