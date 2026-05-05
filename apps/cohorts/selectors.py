"""Cohorts (class groups) read-side selectors."""

from .models import CohortItem


def list_active():
    return CohortItem.objects.filter(is_active=True)
