"""Printing (server side) read-side selectors."""

from .models import PrintingItem


def list_active():
    return PrintingItem.objects.filter(is_active=True)
