"""AI read-side selectors."""

from .models import AiItem


def list_active():
    return AiItem.objects.filter(is_active=True)
