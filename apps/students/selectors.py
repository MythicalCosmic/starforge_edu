"""Students read-side selectors."""

from .models import StudentItem


def list_active():
    return StudentItem.objects.filter(is_active=True)
