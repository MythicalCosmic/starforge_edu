"""Small utility helpers used across apps."""

from __future__ import annotations

import hashlib
import secrets


def generate_otp(length: int = 6) -> str:
    """Cryptographically random numeric OTP."""

    upper = 10**length
    return f"{secrets.randbelow(upper):0{length}d}"


def stable_hash(value: str) -> str:
    """SHA-256 hash, hex. Used for prompt-cache keys and idempotency keys."""

    return hashlib.sha256(value.encode("utf-8")).hexdigest()
