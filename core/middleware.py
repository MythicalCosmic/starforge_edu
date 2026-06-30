"""Project middleware.

Three concerns, ordered in `config.settings.base.MIDDLEWARE`:

1. `RequestIDMiddleware` (outermost) — correlation id on every request/response.
2. `HealthCheckMiddleware` (before tenant resolution) — liveness/readiness probes
   that answer on any Host header without a tenant.
3. `InactiveTenantMiddleware` (after tenant resolution) — 503 on a deactivated
   Center (Lane B / D1-LB-6).
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable

from django.db import connection
from django.http import HttpRequest, HttpResponse, JsonResponse
from django_tenants.utils import get_public_schema_name

from core.logging_filters import request_id_var

REQUEST_ID_HEADER = "X-Request-ID"

# Inbound ids are attacker-controlled and end up in log lines (`req={request_id}`)
# and the response header — restrict to a safe charset and a sane length so a
# crafted value cannot forge/split log records or trigger BadHeaderError.
REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

GetResponse = Callable[[HttpRequest], HttpResponse]


class RequestIDMiddleware:
    """Honor a well-formed inbound ``X-Request-ID`` (charset/length validated) or
    mint a uuid4, expose it to the logging filters for the life of the request,
    and echo it on the response.
    """

    def __init__(self, get_response: GetResponse) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        inbound = request.headers.get(REQUEST_ID_HEADER, "")
        request_id = inbound if REQUEST_ID_RE.fullmatch(inbound) else uuid.uuid4().hex
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


# ---------------------------------------------------------------------------
# JSON error envelope — project-wide (backend API: never serve an HTML error)
# ---------------------------------------------------------------------------

# Map an HTTP status to a stable, branchable error code (mirrors the DRF
# envelope in core.exceptions so API and non-API errors are indistinguishable).
_ERROR_CODES = {
    400: "bad_request",
    401: "authentication_failed",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    406: "not_acceptable",
    415: "unsupported_media_type",
    429: "throttled",
    500: "server_error",
    502: "bad_gateway",
    503: "service_unavailable",
}
_ERROR_DETAILS = {
    400: "Bad request.",
    401: "Authentication credentials were not provided or are invalid.",
    403: "You do not have permission to perform this action.",
    404: "Resource not found.",
    405: "Method not allowed.",
    429: "Too many requests.",
    500: "Internal server error.",
    503: "Service unavailable.",
}


def _error_envelope(status_code: int) -> dict[str, dict[str, str]]:
    return {
        "error": {
            "code": _ERROR_CODES.get(status_code, "error"),
            "detail": _ERROR_DETAILS.get(status_code, "An error occurred."),
        }
    }


# ROOT_URLCONF / PUBLIC_SCHEMA_URLCONF handlerXXX — keep Django's own error
# responses (unmatched URL, uncaught 500, CSRF 403) as JSON, not HTML templates.
def json_404(request: HttpRequest, exception: object | None = None) -> JsonResponse:
    return JsonResponse(_error_envelope(404), status=404)


def json_400(request: HttpRequest, exception: object | None = None) -> JsonResponse:
    return JsonResponse(_error_envelope(400), status=400)


def json_403(request: HttpRequest, exception: object | None = None) -> JsonResponse:
    return JsonResponse(_error_envelope(403), status=403)


def json_500(request: HttpRequest) -> JsonResponse:
    return JsonResponse(_error_envelope(500), status=500)


class JsonErrorResponseMiddleware:
    """Guarantee every error response is JSON, project-wide.

    DRF endpoints already emit the ``{"error": {...}}`` envelope via
    ``core.exceptions.drf_exception_handler``. This is the safety net for everything
    that does NOT pass through DRF — an unmatched URL, a non-DRF view, the admin, and
    (crucially) the DEBUG technical 404/500 pages — rewriting any HTML error response
    into the same envelope so an API/mobile client never receives an HTML page.

    Sits just below ``RequestIDMiddleware`` so it runs late on the way out: it MUTATES
    the response in place (never builds a new one), preserving headers inner middleware
    set — CORS, ``Retry-After`` — so a browser SPA can still read the error body.
    """

    def __init__(self, get_response: GetResponse) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        return self._jsonify(self.get_response(request))

    @staticmethod
    def _jsonify(response: HttpResponse) -> HttpResponse:
        if getattr(response, "streaming", False) or response.status_code < 400:
            return response
        if "text/html" not in response.get("Content-Type", ""):
            return response  # already JSON (DRF) or a non-HTML body (e.g. a PDF)
        import json

        response.content = json.dumps(_error_envelope(response.status_code)).encode("utf-8")
        response["Content-Type"] = "application/json"
        return response
