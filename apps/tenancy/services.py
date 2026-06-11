"""Tenancy services — write-side orchestration for tenant lifecycle."""

from __future__ import annotations

import re

from django.db import connection, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django_tenants.utils import schema_context

from core.exceptions import ConflictException, ValidationException

from .models import Center, Domain

# Postgres-safe schema names: lowercase, starts with a letter, ≤ 63 chars.
SLUG_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
RESERVED_SLUGS = {"public", "admin", "www", "api", "static", "media"}


def _validate_slug(slug: str) -> str:
    slug = slug.lower().strip()
    if not SLUG_RE.match(slug):
        raise ValidationException(
            _("Slug must be lowercase letters, digits and underscores, starting with a letter."),
            code="slug_invalid",
        )
    if slug in RESERVED_SLUGS:
        raise ValidationException(_("That slug is reserved."), code="slug_reserved")
    if Center.objects.filter(slug=slug).exists() or Center.objects.filter(schema_name=slug).exists():
        raise ValidationException(_("That slug is already taken."), code="slug_taken")
    return slug


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
    """Create a Center + its primary Domain (triggers schema creation) and seed
    its CenterSettings singleton (TD-13)."""

    slug = _validate_slug(slug)

    center = Center.objects.create(
        name=name,
        slug=slug,
        schema_name=slug,
        contact_name=contact_name,
        contact_phone=contact_phone,
        contact_email=contact_email,
    )
    Domain.objects.create(domain=primary_domain, tenant=center, is_primary=True)

    # The schema + tenant tables now exist (auto_create_schema). Seed settings.
    with schema_context(center.schema_name):
        from apps.org.models import CenterSettings

        CenterSettings.load()

    return center


def delete_center(center: Center, *, force: bool = False) -> None:
    """Drop a Center and its schema. Refuses a populated tenant unless forced."""
    with schema_context(center.schema_name):
        from apps.users.models import User

        user_count = User.objects.count()
    if user_count > 0 and not force:
        raise ValidationException(
            _("Center still has users; pass force=True to delete."), code="center_not_empty"
        )
    center.delete(force_drop=True)


def archive_center(center: Center) -> Center:
    """Soft-archive: rename the schema out of the way and deactivate the Center.

    Uses raw `ALTER SCHEMA RENAME` (no ORM equivalent; the schema name is
    slug-validated so it is injection-safe — WORKLOG justification)."""
    now = timezone.now()
    old_schema = center.schema_name
    new_schema = f"_archived_{old_schema}_{now:%Y%m%d}"
    with connection.cursor() as cursor:
        cursor.execute(f'ALTER SCHEMA "{old_schema}" RENAME TO "{new_schema}"')
    center.schema_name = new_schema
    center.is_active = False
    center.archived_at = now
    center.save(update_fields=["schema_name", "is_active", "archived_at"])
    return center


@transaction.atomic
def set_primary_domain(center: Center, domain_id: int) -> Domain:
    """Make exactly one Domain primary for a Center, atomically."""
    domain = Domain.objects.select_for_update().filter(tenant=center, pk=domain_id).first()
    if domain is None:
        raise ConflictException(_("Domain does not belong to this center."), code="not_found")
    Domain.objects.filter(tenant=center, is_primary=True).exclude(pk=domain.pk).update(is_primary=False)
    domain.is_primary = True
    domain.save(update_fields=["is_primary"])
    return domain


def add_domain(center: Center, *, domain: str, is_primary: bool = False) -> Domain:
    """Attach a hostname to a Center (TXT ownership check stubbed — O-8)."""
    if Domain.objects.filter(domain=domain).exists():
        raise ValidationException(_("That domain is already registered."), code="domain_taken")
    row = Domain.objects.create(domain=domain, tenant=center, is_primary=False)
    if is_primary:
        set_primary_domain(center, row.pk)
        row.refresh_from_db()
    return row


def verify_domain_txt(domain: str) -> bool:
    """[OWNER:O-8] DNS TXT ownership verification — mock passes until creds land."""
    return True
