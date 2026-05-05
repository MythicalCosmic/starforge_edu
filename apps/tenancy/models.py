"""Tenant model: Center + Domain.

Center is the tenant — each row owns a Postgres schema. Domain maps
hostnames (subdomains) to Centers. These models live ONLY in the public
schema (apps.tenancy is in SHARED_APPS only).

DO NOT add tenant-scoped fields here (e.g. branch references). Those
belong in apps.org under the tenant schemas.
"""

from __future__ import annotations

from django.db import models
from django_tenants.models import DomainMixin, TenantMixin


class Center(TenantMixin):
    """A customer education center. One row = one Postgres schema."""

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=100, unique=True)

    # Contact + ops metadata (platform-level, not tenant-scoped).
    contact_name = models.CharField(max_length=200, blank=True)
    contact_phone = models.CharField(max_length=32, blank=True)
    contact_email = models.EmailField(blank=True)

    is_active = models.BooleanField(default=True)
    on_trial = models.BooleanField(default=True)
    trial_ends_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # django-tenants will run TENANT_APPS migrations the first time this
    # row is saved when auto_create_schema is True.
    auto_create_schema = True
    auto_drop_schema = False  # never auto-drop in prod; explicit deletion only

    class Meta:
        ordering = ("name",)

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.name} ({self.schema_name})"


class Domain(DomainMixin):
    """Hostname → Center mapping. One Center can have multiple Domains."""

    pass
