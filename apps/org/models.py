"""Per-tenant organizational structure: Branch + Department.

Lives in tenant schemas only. A row's tenant is the schema it lives in;
no FK to Center is needed because django-tenants enforces isolation at
the connection level.
"""

from __future__ import annotations

from django.db import models


class Branch(models.Model):
    """A physical location of the education center (city / building)."""

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=100, unique=True)
    address = models.CharField(max_length=512, blank=True)
    phone = models.CharField(max_length=32, blank=True)

    timezone = models.CharField(max_length=64, default="Asia/Tashkent")
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)
        verbose_name_plural = "Branches"

    def __str__(self) -> str:  # pragma: no cover
        return self.name


class Department(models.Model):
    """A teaching/admin unit inside a Branch (math, languages, finance, etc.)."""

    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="departments")
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=100)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = (("branch", "slug"),)
        ordering = ("branch", "name")

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.branch.name}/{self.name}"


class Room(models.Model):
    """A bookable room inside a Branch (used by Schedule for conflict checks)."""

    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="rooms")
    name = models.CharField(max_length=120)
    capacity = models.PositiveIntegerField(default=0)
    equipment = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = (("branch", "name"),)
        ordering = ("branch", "name")

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.branch.name}/{self.name}"
