"""Access-config write services (A-2)."""

from __future__ import annotations

from django.utils.translation import gettext_lazy as _

from apps.access.models import RolePermissionOverride
from core.exceptions import ValidationException


def set_override(
    *, role: str, permission: str, effect: str, actor=None, note: str = ""
) -> RolePermissionOverride:
    """Create or update the override for (role, permission). The model's save()
    invalidates the per-tenant permission cache on commit."""
    if permission == "*:*":
        # Mirror the serializer + DB CheckConstraint at the service layer so every
        # programmatic caller is covered (the wildcard protects director authority).
        raise ValidationException(
            _("The master wildcard '*:*' cannot be overridden."), code="wildcard_not_overridable"
        )
    if permission.partition(":")[0] == "access":
        # Permission management is not delegable — keeps it director-only (*:*).
        raise ValidationException(
            _("The 'access' resource cannot be overridden."), code="access_not_overridable"
        )
    obj, _created = RolePermissionOverride.objects.update_or_create(
        role=role,
        permission=permission,
        defaults={"effect": effect, "note": note, "created_by": actor},
    )
    return obj


def clear_override(*, override: RolePermissionOverride) -> None:
    override.delete()
