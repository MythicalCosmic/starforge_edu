"""Branch / Department read selectors."""

from __future__ import annotations

from .models import Branch, Department


def list_branches():
    return Branch.objects.filter(is_active=True)


def list_departments_in_branch(branch_id: int):
    return Department.objects.filter(branch_id=branch_id, is_active=True)
