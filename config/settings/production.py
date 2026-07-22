"""Production settings."""

import json
from pathlib import Path
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured
from django.utils.csp import CSP

from .base import *  # noqa: F403
from .base import (
    AI_ENABLED,
    CORS_ALLOWED_ORIGINS,
    CSRF_TRUSTED_ORIGINS,
    EMAIL_ENABLED,
    FIELD_ENCRYPTION_KEY,
    FISCALIZATION_ENABLED,
    PUSH_NOTIFICATIONS_ENABLED,
    SMS_ENABLED,
    env,
)

DEBUG = False

# Only platform-owned suffixes may skip customer DNS verification. This is
# deliberately empty unless the operator names the deployment's own base domain.
DOMAIN_VERIFICATION_TRUSTED_SUFFIXES = env.list(
    "DOMAIN_VERIFICATION_TRUSTED_SUFFIXES",
    default=[],
)

# Fail fast on insecure defaults — base.py ships dev-friendly fallbacks
# (`dev-only-CHANGE-ME`, ALLOWED_HOSTS=["*"]) that must NEVER reach production:
# the default SECRET_KEY would let anyone forge signed data/sessions, and a wildcard
# host disables Host-header validation.
SECRET_KEY = env("SECRET_KEY")
# Reject the dev default AND any short/low-entropy key because Django signs security-
# sensitive values with it (get_random_secret_key() produces 50-character values).
if not SECRET_KEY or SECRET_KEY == "dev-only-CHANGE-ME" or len(SECRET_KEY) < 50:
    raise ImproperlyConfigured(
        "SECRET_KEY must be a unique, secret value of at least 50 characters in production."
    )

ALLOWED_HOSTS = env("ALLOWED_HOSTS")
if not ALLOWED_HOSTS or "*" in ALLOWED_HOSTS:
    raise ImproperlyConfigured("ALLOWED_HOSTS must be set explicitly in production (no wildcard).")

# TD-11 / O-11: encrypted fields are unreadable without this — fail fast.
if not FIELD_ENCRYPTION_KEY:
    raise ImproperlyConfigured("FIELD_ENCRYPTION_KEY must be set in production (TD-11).")

# CORS/CSRF must be an explicit allowlist in prod, never a wildcard (D5-A-3):
# CORS_ALLOW_CREDENTIALS is True, so a wildcard origin would expose authenticated
# responses to any site.
if globals().get("CORS_ALLOW_ALL_ORIGINS"):
    raise ImproperlyConfigured("CORS_ALLOW_ALL_ORIGINS must be False in production.")
if any("*" in origin for origin in CORS_ALLOWED_ORIGINS):
    raise ImproperlyConfigured("CORS_ALLOWED_ORIGINS must not contain a wildcard in production.")
if any("*" in origin for origin in CSRF_TRUSTED_ORIGINS):
    raise ImproperlyConfigured("CSRF_TRUSTED_ORIGINS must not contain a wildcard in production.")

# Production terminates TLS behind a reverse proxy (SECURE_PROXY_SSL_HEADER below),
# so NUM_PROXIES MUST reflect the trusted hop count — otherwise client_ip / DRF's
# get_ident resolve every client to the proxy's IP and all IP-keyed throttles
# (login_ip, otp_ip, ...) collapse into one shared bucket.
if env("NUM_PROXIES") < 1:
    raise ImproperlyConfigured(
        "NUM_PROXIES must be set to the number of trusted reverse-proxy hops (>=1) in production; "
        "IP-keyed throttles depend on it."
    )


def _require_service_url(name: str, *, schemes: tuple[str, ...]) -> str:
    value = env(name)
    parsed = urlsplit(value)
    if not value or parsed.scheme not in schemes or not parsed.hostname:
        raise ImproperlyConfigured(f"{name} must be an explicit production service URL.")
    return value


# Never inherit base.py's developer services or published local credentials in
# production. A misspelled secret must stop the release, not connect the API to
# an unrelated localhost database/cache.
_require_service_url("DATABASE_URL", schemes=("postgres", "postgresql"))
_require_service_url("REDIS_URL", schemes=("redis", "rediss"))
_media_bucket_name = env("AWS_STORAGE_BUCKET_NAME")
_static_bucket_name = env("AWS_STATIC_BUCKET_NAME")
if not _media_bucket_name or not _static_bucket_name or _media_bucket_name == _static_bucket_name:
    raise ImproperlyConfigured(
        "AWS_STORAGE_BUCKET_NAME and AWS_STATIC_BUCKET_NAME must name distinct production buckets."
    )
AWS_S3_PUBLIC_ENDPOINT_URL = _require_service_url("AWS_S3_PUBLIC_ENDPOINT_URL", schemes=("https",)).rstrip(
    "/"
)
_storage_public_url = urlsplit(AWS_S3_PUBLIC_ENDPOINT_URL)
if (
    _storage_public_url.username
    or _storage_public_url.password
    or _storage_public_url.path not in {"", "/"}
    or _storage_public_url.query
    or _storage_public_url.fragment
    or "*" in _storage_public_url.netloc
    or _storage_public_url.hostname in {"localhost", "minio", "127.0.0.1", "::1"}
):
    raise ImproperlyConfigured(
        "AWS_S3_PUBLIC_ENDPOINT_URL must be a browser-reachable HTTPS origin without credentials."
    )
if EMAIL_ENABLED and env("EMAIL_HOST").strip().lower() in {"", "localhost", "127.0.0.1", "::1"}:
    raise ImproperlyConfigured("EMAIL_HOST must be configured explicitly in production.")

SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 365
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

# Bearer credentials must never appear in URLs, access logs, browser history, or
# reverse-proxy telemetry. WebSocket clients authenticate with the negotiated
# ``bearer.<token>`` subprotocol instead.
WEBSOCKET_ALLOW_QUERY_TOKEN = False
HEALTH_READY_CACHE_SECONDS = 2.0
HEALTH_REQUIRE_CELERY_HEARTBEAT = True

# Django 6 ships a native CSP middleware. Keep the API/admin baseline strict;
# inline styles remain allowed for Django admin compatibility, while scripts,
# frames, plugins, and form targets stay same-origin/fail-closed.
MIDDLEWARE.insert(  # noqa: F405
    MIDDLEWARE.index("django.middleware.security.SecurityMiddleware") + 1,  # noqa: F405
    "django.middleware.csp.ContentSecurityPolicyMiddleware",
)
_storage_public_origin = f"{_storage_public_url.scheme}://{_storage_public_url.netloc}"
SECURE_CSP = {
    "default-src": [CSP.SELF],
    "base-uri": [CSP.SELF],
    "object-src": [CSP.NONE],
    "frame-ancestors": [CSP.NONE],
    "form-action": [CSP.SELF],
    "script-src": [CSP.SELF, _storage_public_origin],
    "style-src": [CSP.SELF, CSP.UNSAFE_INLINE, _storage_public_origin],
    "img-src": [CSP.SELF, "data:", _storage_public_origin],
    "font-src": [CSP.SELF, "data:", _storage_public_origin],
    "connect-src": [CSP.SELF, "wss:", _storage_public_origin],
}

# Never mock real SMS in prod.
ESKIZ_USE_MOCK = False

# Never mock the Anthropic API in prod (D4-LA-2). Requires a real key [OWNER:O-2].
ANTHROPIC_USE_MOCK = False

# Never ship a mock money/fiscal/push integration to prod. base.py defaults these
# to True (mock-first, TD-2) and only ESKIZ/ANTHROPIC were forced off here, so a
# misconfigured prod could silently fake payments/fiscalization/push. Force them
# all real — real provider credentials are then required [OWNER:O-5/O-7].
CLICK_USE_MOCK = False
PAYME_USE_MOCK = False
UZUM_USE_MOCK = False
SOLIQ_USE_MOCK = False
FCM_USE_MOCK = False
PLATFORM_PAYMENTS_USE_MOCK = False


def _require_credentials(integration: str, *names: str) -> None:
    missing = [name for name in names if not str(env(name)).strip()]
    if missing:
        raise ImproperlyConfigured(
            f"{integration} is enabled in production but required credentials are missing: "
            + ", ".join(missing)
        )


def _validate_firebase_credentials() -> None:
    path = Path(env("FCM_CREDENTIALS_FILE"))
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ImproperlyConfigured(
            "Firebase push is enabled but FCM_CREDENTIALS_FILE is not readable service-account JSON."
        ) from exc
    required = {"type", "project_id", "private_key", "client_email"}
    if payload.get("type") != "service_account" or not all(payload.get(key) for key in required):
        raise ImproperlyConfigured("Firebase push is enabled but its service-account JSON is incomplete.")


if SMS_ENABLED:
    _require_credentials("Eskiz SMS", "ESKIZ_EMAIL", "ESKIZ_PASSWORD", "ESKIZ_FROM")
if AI_ENABLED:
    _require_credentials("Anthropic AI", "ANTHROPIC_API_KEY")
if FISCALIZATION_ENABLED:
    _require_credentials("Soliq fiscalization", "SOLIQ_API_URL", "SOLIQ_API_TOKEN")
if PUSH_NOTIFICATIONS_ENABLED:
    _require_credentials("Firebase push", "FCM_CREDENTIALS_FILE")
    _validate_firebase_credentials()

# Structured JSON logging in production only (D1-LA-10) — dev/test stay human.
LOGGING["formatters"]["json"] = {  # type: ignore[index]  # noqa: F405
    "()": "core.logging_filters.JsonFormatter",
}
LOGGING["handlers"]["console"]["formatter"] = "json"  # type: ignore[index]  # noqa: F405

# Sentry — config-only (D1-LA-13 / O-10). No effect unless SENTRY_DSN is set,
# so dev/test/CI never need the dependency installed.
SENTRY_DSN = env("SENTRY_DSN", default="")
if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration()],
        traces_sample_rate=env.float("SENTRY_TRACES_SAMPLE_RATE", default=0.0),
        send_default_pii=False,
        environment=env("SENTRY_ENVIRONMENT", default="production"),
    )

# Static files served via S3 in prod.
STORAGES["staticfiles"] = {  # noqa: F405
    "BACKEND": "infrastructure.storage.backends.DualEndpointS3Storage",
    "OPTIONS": {
        "bucket_name": _static_bucket_name,
        "endpoint_url": env("AWS_S3_ENDPOINT_URL") or None,
        "access_key": env("AWS_S3_ACCESS_KEY_ID"),
        "secret_key": env("AWS_S3_SECRET_ACCESS_KEY"),
        "region_name": env("AWS_S3_REGION_NAME"),
        "addressing_style": "path",
        "signature_version": "s3v4",
        "querystring_auth": False,
    },
}
