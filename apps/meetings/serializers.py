from __future__ import annotations

from rest_framework import serializers

from apps.meetings.models import MeetingAttendee, StaffMeeting
from apps.org.models import Branch
from apps.users.models import User
from core.permissions import Role

# Meetings are staff coordination — invitees must be staff, never students/parents.
_STAFF_ROLES = tuple(r for r in Role.ALL if r not in (Role.STUDENT, Role.PARENT))


class MeetingAttendeeSerializer(serializers.ModelSerializer):
    class Meta:
        model = MeetingAttendee
        fields = ("id", "user", "response", "responded_at")
        read_only_fields = fields


class StaffMeetingSerializer(serializers.ModelSerializer):
    attendees = MeetingAttendeeSerializer(many=True, read_only=True)

    class Meta:
        model = StaffMeeting
        fields = (
            "id",
            "title",
            "agenda",
            "branch",
            "starts_at",
            "ends_at",
            "location",
            "status",
            "attendees",
            "created_by",
            "cancelled_by",
            "cancelled_at",
            "created_at",
        )
        read_only_fields = fields


class ScheduleMeetingSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200)
    agenda = serializers.CharField(required=False, allow_blank=True, default="")
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    location = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    branch = serializers.PrimaryKeyRelatedField(
        queryset=Branch.objects.filter(archived_at__isnull=True), required=False, allow_null=True
    )
    attendees = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(
            is_active=True,
            role_memberships__revoked_at__isnull=True,
            role_memberships__role__in=_STAFF_ROLES,
        ).distinct(),
        many=True,
        allow_empty=False,
    )


class RespondMeetingSerializer(serializers.Serializer):
    response = serializers.ChoiceField(
        choices=(MeetingAttendee.Response.ACCEPTED, MeetingAttendee.Response.DECLINED)
    )
