"""Tenancy services — write-side orchestration for tenant lifecycle."""

from __future__ import annotations

from django.db import transaction

from .models import Center, Domain


@transaction.atomic
def provision_center(
    *,
    name: str,
    slug: str,
    primary_domain: str,
    contact_name: str = "",
    contact_phone: str = "",
    contact_email: str = "",
) -> Center:
    """Create a Center + its primary Domain. Triggers schema creation."""

    center = Center.objects.create(
        name=name,
        slug=slug,
        schema_name=slug,  # schema is the slug; Postgres-safe slugs only
        contact_name=contact_name,
        contact_phone=contact_phone,
        contact_email=contact_email,
    )
    Domain.objects.create(domain=primary_domain, tenant=center, is_primary=True)
    return center
