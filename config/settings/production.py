"""Production settings."""

from .base import *  # noqa: F403
from .base import env

DEBUG = False
ALLOWED_HOSTS = env("ALLOWED_HOSTS")

SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 365
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
X_FRAME_OPTIONS = "DENY"

# Never mock real SMS in prod.
ESKIZ_USE_MOCK = False

# Static files served via S3 in prod.
STORAGES["staticfiles"] = {  # type: ignore[name-defined]  # noqa: F405
    "BACKEND": "storages.backends.s3.S3Storage",
    "OPTIONS": {
        "bucket_name": env("AWS_STATIC_BUCKET_NAME", default=env("AWS_STORAGE_BUCKET_NAME")),
        "endpoint_url": env("AWS_S3_ENDPOINT_URL") or None,
        "access_key": env("AWS_S3_ACCESS_KEY_ID"),
        "secret_key": env("AWS_S3_SECRET_ACCESS_KEY"),
        "region_name": env("AWS_S3_REGION_NAME"),
        "addressing_style": "path",
        "signature_version": "s3v4",
    },
}
