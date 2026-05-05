"""Schedule read-side selectors."""

from .models import ScheduleItem


def list_active():
    return ScheduleItem.objects.filter(is_active=True)
