"""Finance read-side selectors."""

from .models import FinanceItem


def list_active():
    return FinanceItem.objects.filter(is_active=True)
