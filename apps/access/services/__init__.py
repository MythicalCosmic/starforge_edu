"""Access-config write services (A-2).

``set_override`` / ``clear_override`` are the programmatic upsert/delete API (imported
by other apps' flows + tests); the CRUD service in ``services/v1`` handles the HTTP
endpoints. Both go through standard ORM writes — the override map is read live per
request (no cross-request cache), so a change takes effect on the very next request.
"""

from __future__ import annotations

from django.utils.translation import gettext_lazy as _

from apps.access.models import RolePermissionOverride
from core.exceptions import ValidationException


def set_override(
    *, role: str, permission: str, effect: str, actor=None, note: str = ""
) -> RolePermissionOverride:
    """Create or update the override for (role, permission)."""
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
