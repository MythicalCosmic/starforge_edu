"""Audit read-side selectors."""

from .models import AuditItem


def list_active():
    return AuditItem.objects.filter(is_active=True)
