from rest_framework import serializers

from .models import Center, Domain


class DomainSerializer(serializers.ModelSerializer):
    class Meta:
        model = Domain
        fields = ("id", "domain", "is_primary")


class DomainCreateSerializer(serializers.Serializer):
    domain = serializers.CharField(max_length=253)
    is_primary = serializers.BooleanField(default=False)


class CenterSerializer(serializers.ModelSerializer):
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
