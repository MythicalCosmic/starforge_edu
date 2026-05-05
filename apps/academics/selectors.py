"""Academics read-side selectors."""

from .models import AcademicItem


def list_active():
    return AcademicItem.objects.filter(is_active=True)
