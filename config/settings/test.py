"""Test settings — fast, deterministic, no external services."""

from .base import *  # noqa: F403

DEBUG = False
SECRET_KEY = "test-only-not-secret"
ALLOWED_HOSTS = ["*"]

# Synchronous Celery in tests.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_TASK_CLS = "celery.app.task:Task"  # bypass tenant-schemas-celery in tests

# In-memory channel layer.
CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}

# Locmem cache.
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

# Local file storage in tests.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# Always mock SMS in tests.
ESKIZ_USE_MOCK = True

# Faster password hashing in tests.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Quiet logs in tests.
LOGGING["loggers"][""]["level"] = "WARNING"  # type: ignore[index]  # noqa: F405
