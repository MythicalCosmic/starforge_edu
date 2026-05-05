"""Redis client wrapper. Uses django.core.cache when possible,
plus a thin direct redis-py client for things django.cache doesn't expose
(e.g. INCR with TTL for OTP rate counting, pub/sub for cross-process events).
"""

from __future__ import annotations

from functools import lru_cache

import redis
from django.conf import settings


@lru_cache(maxsize=1)
def get_redis() -> redis.Redis:
    return redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
