"""Teachers read-side selectors."""

from .models import TeacherItem


def list_active():
    return TeacherItem.objects.filter(is_active=True)
