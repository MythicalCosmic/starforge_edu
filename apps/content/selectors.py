"""Lesson content read-side selectors."""

from .models import ContentItem


def list_active():
    return ContentItem.objects.filter(is_active=True)
