"""Tenancy serializers (PUBLIC schema, platform-staff facing).

Read/write split; no `fields = "__all__"`. The control-center action bodies
(suspend/activate/extend-trial/impersonate/resolve) carry their own tiny
request serializers so OpenAPI documents the shapes.
"""

from __future__ import annotations

from rest_framework import serializers

from .models import Center, Domain, PlatformEvent


class DomainSerializer(serializers.ModelSerializer):
    class Meta:
        model = Domain
        fields = ("id", "domain", "is_primary")


class DomainCreateSerializer(serializers.Serializer):
    domain = serializers.CharField(max_length=253)
    is_primary = serializers.BooleanField(default=False)


class CenterSerializer(serializers.ModelSerializer):
    """Read serializer for a Center (platform staff view)."""

    domains = DomainSerializer(many=True, read_only=True)

    class Meta:
        model = Center
        fields = (
            "id",
            "name",
            "slug",
            "schema_name",
            "contact_name",
            "contact_phone",
            "contact_email",
            "is_active",
            "on_trial",
            "trial_ends_at",
            "archived_at",
            "created_at",
            "domains",
        )
        read_only_fields = ("schema_name", "archived_at", "created_at")


class CenterCreateSerializer(serializers.Serializer):
    """Write serializer for POST /platform/centers/ → services.provision_center."""

    name = serializers.CharField(max_length=200)
    slug = serializers.SlugField(max_length=100)
    primary_domain = serializers.CharField(max_length=253)
    contact_name = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    contact_phone = serializers.CharField(max_length=32, required=False, allow_blank=True, default="")
    contact_email = serializers.EmailField(required=False, allow_blank=True, default="")


class CenterUpdateSerializer(serializers.ModelSerializer):
    """Write serializer for PATCH /platform/centers/<id>/ — contact metadata only.

    Lifecycle (is_active / trial) is changed through the dedicated action
    endpoints, never a blanket PATCH, so each transition is audited.
    """

    class Meta:
        model = Center
        fields = ("name", "contact_name", "contact_phone", "contact_email")


class ExtendTrialSerializer(serializers.Serializer):
    days = serializers.IntegerField(min_value=1, max_value=365)


class SuspendSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=512, required=False, allow_blank=True, default="")


class ImpersonateSerializer(serializers.Serializer):
    user_id = serializers.IntegerField(min_value=1)


class ImpersonationTokenSerializer(serializers.Serializer):
    access = serializers.CharField()
    expires_in = serializers.IntegerField()


class ResolveSerializer(serializers.Serializer):
    """TD-19 resolve payload (read-only response shape)."""

    name = serializers.CharField()
    base_url = serializers.CharField()
    ws_url = serializers.CharField()
    logo = serializers.CharField(allow_blank=True)
    locale = serializers.CharField()


class UsagePointSerializer(serializers.Serializer):
    date = serializers.DateField()
    dau = serializers.IntegerField()
    students = serializers.IntegerField()
    storage_bytes = serializers.IntegerField()
    ai_tokens = serializers.IntegerField()


class UsageResponseSerializer(serializers.Serializer):
    series = UsagePointSerializer(many=True)
    today = UsagePointSerializer()


class PlatformEventSerializer(serializers.ModelSerializer):
    actor_repr = serializers.CharField(source="actor.username", read_only=True, default="")

    class Meta:
        model = PlatformEvent
        fields = ("id", "actor", "actor_repr", "center", "event", "payload", "created_at")
        read_only_fields = fields
