"""Small utility helpers used across apps."""

from __future__ import annotations

import hashlib
import secrets
from typing import TYPE_CHECKING

from django.db import connection

if TYPE_CHECKING:
    from rest_framework.request import Request


def current_schema() -> str:
    """The active django-tenants schema name (one typed access point for it)."""
    return connection.schema_name  # type: ignore[attr-defined]


def client_ip(request: Request) -> str:
    """Best-effort client IP, honoring a single X-Forwarded-For proxy hop."""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "") or ""


def user_agent(request: Request) -> str:
    return request.META.get("HTTP_USER_AGENT", "")[:512]


def generate_otp(length: int = 6) -> str:
    """Cryptographically random numeric OTP."""

    upper = 10**length
    return f"{secrets.randbelow(upper):0{length}d}"


def stable_hash(value: str) -> str:
    """SHA-256 hash, hex. Used for prompt-cache keys and idempotency keys."""

    return hashlib.sha256(value.encode("utf-8")).hexdigest()
