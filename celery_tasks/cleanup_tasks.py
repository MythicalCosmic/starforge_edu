"""Periodic cleanup tasks. Wired via django-celery-beat in admin."""

from __future__ import annotations

from django.utils import timezone

from apps.users.models import OTP
from config.celery import app


@app.task
def purge_expired_otps() -> int:
    deleted, _ = OTP.objects.filter(expires_at__lt=timezone.now()).delete()
    return deleted
