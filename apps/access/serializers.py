from __future__ import annotations

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.access.models import RolePermissionOverride
from core.permissions import Role


class RolePermissionOverrideSerializer(serializers.ModelSerializer):
    class Meta:
        model = RolePermissionOverride
        fields = (
            "id",
            "role",
            "permission",
            "effect",
            "note",
            "created_by",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_by", "created_at", "updated_at")

    def validate_role(self, value: str) -> str:
        if value not in Role.ALL:
            raise serializers.ValidationError(_("Unknown role."))
        return value

    def validate_permission(self, value: str) -> str:
        value = value.strip()
        if value == "*:*":
            # The master wildcard is not overridable — protects the director's
            # authority and blocks escalation-to-everything via this mechanism.
            raise serializers.ValidationError(_("The master wildcard '*:*' cannot be overridden."))
        resource, sep, verb = value.partition(":")
        if not sep or not resource or not verb:
            raise serializers.ValidationError(
                _("Permission must look like 'resource:verb' (e.g. students:write or students:*).")
            )
        if resource == "access":
            # Managing permissions is not delegable through the override system: you
            # cannot grant/revoke who-can-manage-permissions, so it stays director-only
            # (*:*) and a delegate can never escalate control of the system itself.
            raise serializers.ValidationError(
                _("The 'access' resource cannot be overridden (permission management stays director-only).")
            )
        return value

    def validate(self, attrs):
        # Friendly 400 instead of a unique-constraint 500 on duplicate create.
        if self.instance is None:
            role = attrs.get("role")
            permission = attrs.get("permission")
            if RolePermissionOverride.objects.filter(role=role, permission=permission).exists():
                raise serializers.ValidationError(
                    _("An override for this role + permission already exists; update it instead.")
                )
        return attrs
