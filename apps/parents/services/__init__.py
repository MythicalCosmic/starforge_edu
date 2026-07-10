"""Parent / guardian write services (TASKS §6).

Kept as module-level domain functions (not only the layered service classes)
because tests import them directly:
``from apps.parents.services import create_parent, link_guardian``.
"""

from __future__ import annotations

from django.db import transaction
from django.utils.translation import gettext_lazy as _

from apps.parents.models import Guardian, ParentProfile
from apps.users.services import resolve_or_create_user
from core.exceptions import ValidationException


@transaction.atomic
def create_parent(
    *,
    phone: str = "",
    email: str = "",
    first_name: str = "",
    last_name: str = "",
    middle_name: str = "",
    birthdate=None,
    gender: str = "",
    workplace: str = "",
    notes: str = "",
) -> ParentProfile:
    user = resolve_or_create_user(
        phone=phone, email=email, first_name=first_name, last_name=last_name, middle_name=middle_name
    )
    if ParentProfile.objects.filter(user=user).exists():
        raise ValidationException(_("This person already has a parent profile."), code="duplicate_parent")
    return ParentProfile.objects.create(
        user=user,
        # Identity is OWNED by the parent model (role-native auth). name/phone/email
        # mirror the login account during the transition; birthdate/gender live only here.
        first_name=user.first_name,
        last_name=user.last_name,
        middle_name=user.middle_name,
        phone=user.phone or "",
        email=user.email or "",
        birthdate=birthdate,
        gender=gender,
        workplace=workplace,
        notes=notes,
    )


@transaction.atomic
def link_guardian(
    *, parent: ParentProfile, student, relationship: str, is_primary: bool = False, custody_notes: str = ""
) -> Guardian:
    """Link a parent to a student. Enforces one primary guardian per student
    (also a DB constraint) and prevents duplicate links, returning clean 400s."""
    if Guardian.objects.filter(parent=parent, student=student).exists():
        raise ValidationException(_("This guardian link already exists."), code="guardian_exists")
    if is_primary and Guardian.objects.filter(student=student, is_primary=True).exists():
        raise ValidationException(
            _("This student already has a primary guardian."), code="primary_guardian_exists"
        )
    return Guardian.objects.create(
        parent=parent,
        student=student,
        relationship=relationship,
        is_primary=is_primary,
        custody_notes=custody_notes,
    )
