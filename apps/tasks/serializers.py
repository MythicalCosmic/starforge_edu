from __future__ import annotations

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.org.models import Branch, Department
from apps.tasks.models import RoleGrade, Task
from apps.users.models import User
from core.permissions import Role

# Who may be tasked: staff, i.e. everyone except students and parents.
_TASKABLE_ROLES = tuple(r for r in Role.ALL if r not in (Role.STUDENT, Role.PARENT))


class RoleGradeSerializer(serializers.ModelSerializer):
    class Meta:
        model = RoleGrade
        fields = ("id", "role", "level", "label", "created_at", "updated_at")
        read_only_fields = ("id", "created_at", "updated_at")

    def validate_role(self, value: str) -> str:
        if value not in Role.ALL:
            raise serializers.ValidationError(_("Unknown role."))
        return value


class TaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = Task
        fields = (
            "id",
            "title",
            "description",
            "status",
            "priority",
            "assignee",
            "department",
            "branch",
            "due_at",
            "created_by",
            "completed_at",
            "created_at",
        )
        read_only_fields = ("id", "status", "created_by", "completed_at", "created_at")


class TaskCreateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    priority = serializers.ChoiceField(
        choices=Task.Priority.choices, required=False, default=Task.Priority.NORMAL
    )
    assignee = serializers.PrimaryKeyRelatedField(
        # Only staff (an active staff RoleMembership in this center) can be tasked —
        # never a student/parent who could never see it, nor a membership-less user.
        queryset=User.objects.filter(
            is_active=True,
            role_memberships__revoked_at__isnull=True,
            role_memberships__role__in=_TASKABLE_ROLES,
        ).distinct(),
        required=False,
        allow_null=True,
    )
    department = serializers.PrimaryKeyRelatedField(
        queryset=Department.objects.all(), required=False, allow_null=True
    )
    branch = serializers.PrimaryKeyRelatedField(
        queryset=Branch.objects.filter(archived_at__isnull=True), required=False, allow_null=True
    )
    due_at = serializers.DateTimeField(required=False, allow_null=True)


class TaskAssignSerializer(serializers.Serializer):
    assignee = serializers.PrimaryKeyRelatedField(
        # Only staff (an active staff RoleMembership in this center) can be tasked —
        # never a student/parent who could never see it, nor a membership-less user.
        queryset=User.objects.filter(
            is_active=True,
            role_memberships__revoked_at__isnull=True,
            role_memberships__role__in=_TASKABLE_ROLES,
        ).distinct(),
        required=False,
        allow_null=True,
    )
    department = serializers.PrimaryKeyRelatedField(
        queryset=Department.objects.all(), required=False, allow_null=True
    )

    def validate(self, attrs):
        if "assignee" not in attrs and "department" not in attrs:
            raise serializers.ValidationError(_("Provide an assignee and/or a department."))
        return attrs


class TaskTransitionSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Task.Status.choices)
