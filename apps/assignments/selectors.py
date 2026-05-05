"""Assignments (homework) read-side selectors."""

from .models import AssignmentItem


def list_active():
    return AssignmentItem.objects.filter(is_active=True)
