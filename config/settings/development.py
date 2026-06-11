"""Development settings — verbose, permissive, hot-reloadable."""

import base64

from .base import *  # noqa: F403
from .base import env

DEBUG = True
ALLOWED_HOSTS = ["*"]

# Deterministic throwaway field-encryption key (TD-11) — dev only, never prod.
FIELD_ENCRYPTION_KEY = base64.urlsafe_b64encode(b"starforge-dev-fieldenc-key-32byt").decode()

# Allow *.localhost for django-tenants subdomain routing in dev.
INTERNAL_IPS = ["127.0.0.1"]

# Verbose SQL logging when DEBUG_SQL=true.
if env.bool("DEBUG_SQL", default=False):
    LOGGING_DB = {
        "django.db.backends": {"level": "DEBUG", "handlers": ["console"], "propagate": False},
    }

# Send emails to stdout in dev.
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Looser CORS in dev.
CORS_ALLOW_ALL_ORIGINS = True

# Eskiz mock by default in dev.
ESKIZ_USE_MOCK = True

# silence Django security checks that don't apply locally
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
