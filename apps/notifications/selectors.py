"""Notifications read-side selectors."""

from .models import NotificationItem


def list_active():
    return NotificationItem.objects.filter(is_active=True)
