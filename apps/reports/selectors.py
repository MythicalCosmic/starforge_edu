"""Reports read-side selectors."""

from .models import ReportItem


def list_active():
    return ReportItem.objects.filter(is_active=True)
