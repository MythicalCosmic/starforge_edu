"""RequestIDMiddleware + HealthCheckMiddleware unit tests (D1-LA). No DB —
the DB/Redis probes are mocked, requests come from RequestFactory."""

import json
import re
from unittest import mock

from django.http import HttpResponse
from django.test import RequestFactory

from core.middleware import HealthCheckMiddleware, RequestIDMiddleware

UUID_HEX_RE = re.compile(r"^[0-9a-f]{32}$")


def _ok(request):
    return HttpResponse("ok")


def _request(**extra):
    return RequestFactory().get("/some/path/", **extra)


# ---------------------------------------------------------------------------
# RequestIDMiddleware
# ---------------------------------------------------------------------------


def test_request_id_valid_inbound_is_echoed():
    middleware = RequestIDMiddleware(_ok)
    request = _request(HTTP_X_REQUEST_ID="req-abc.123_DEF")
    response = middleware(request)
    assert response["X-Request-ID"] == "req-abc.123_DEF"
    assert request.request_id == "req-abc.123_DEF"


def test_request_id_minted_when_absent():
    middleware = RequestIDMiddleware(_ok)
    response = middleware(_request())
    assert UUID_HEX_RE.fullmatch(response["X-Request-ID"])


def test_request_id_minted_when_inbound_has_newline():
    middleware = RequestIDMiddleware(_ok)
    inbound = "forged\ninjected-log-line"
    response = middleware(_request(HTTP_X_REQUEST_ID=inbound))
    assert response["X-Request-ID"] != inbound
    assert UUID_HEX_RE.fullmatch(response["X-Request-ID"])


def test_request_id_minted_when_inbound_too_long():
    middleware = RequestIDMiddleware(_ok)
    inbound = "a" * 65
    response = middleware(_request(HTTP_X_REQUEST_ID=inbound))
    assert response["X-Request-ID"] != inbound
    assert UUID_HEX_RE.fullmatch(response["X-Request-ID"])


# ---------------------------------------------------------------------------
# HealthCheckMiddleware
# ---------------------------------------------------------------------------


def _boom(request):  # probes must short-circuit before the rest of the stack
    raise AssertionError("health probe should not reach get_response")


def test_healthz_live_returns_200():
    response = HealthCheckMiddleware(_boom)(RequestFactory().get("/healthz/live"))
    assert response.status_code == 200
    assert json.loads(response.content) == {"status": "ok"}


def test_healthz_ready_503_when_db_down():
    with mock.patch("core.middleware.connection") as conn:
        conn.cursor.side_effect = Exception("db down")
        response = HealthCheckMiddleware(_boom)(RequestFactory().get("/healthz/ready"))
    assert response.status_code == 503
    body = json.loads(response.content)
    assert body["error"]["code"] == "not_ready"
    assert body["error"]["detail"] == "Database unavailable."


def test_healthz_ready_503_when_redis_down():
    with (
        mock.patch("core.middleware.connection", mock.MagicMock()),  # DB answers
        mock.patch("infrastructure.cache.redis_client.get_redis") as get_redis,
    ):
        get_redis.return_value.ping.side_effect = Exception("redis down")
        response = HealthCheckMiddleware(_boom)(RequestFactory().get("/healthz/ready"))
    assert response.status_code == 503
    body = json.loads(response.content)
    assert body["error"]["code"] == "not_ready"
    assert body["error"]["detail"] == "Cache unavailable."


def test_healthz_ready_200_when_all_healthy():
    with (
        mock.patch("core.middleware.connection", mock.MagicMock()),
        mock.patch("infrastructure.cache.redis_client.get_redis") as get_redis,
    ):
        get_redis.return_value.ping.return_value = True
        response = HealthCheckMiddleware(_boom)(RequestFactory().get("/healthz/ready"))
    assert response.status_code == 200
    assert json.loads(response.content) == {"status": "ready"}
