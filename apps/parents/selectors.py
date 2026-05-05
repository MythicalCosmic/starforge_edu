"""Parents read-side selectors."""

from .models import ParentItem


def list_active():
    return ParentItem.objects.filter(is_active=True)
