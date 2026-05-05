"""Attendance read-side selectors."""

from .models import AttendanceItem


def list_active():
    return AttendanceItem.objects.filter(is_active=True)
