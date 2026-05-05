"""Staging settings — production-shaped but with mock SMS and verbose logs."""

from .production import *  # noqa: F403

DEBUG = False
ESKIZ_USE_MOCK = True  # never bill real SMS from staging
LOGGING["loggers"][""]["level"] = "DEBUG"  # type: ignore[index]  # noqa: F405
