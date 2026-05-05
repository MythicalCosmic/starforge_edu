"""Payments read-side selectors."""

from .models import PaymentItem


def list_active():
    return PaymentItem.objects.filter(is_active=True)
