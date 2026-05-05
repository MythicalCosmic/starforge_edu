from rest_framework import serializers

from .models import Center, Domain


class DomainSerializer(serializers.ModelSerializer):
    class Meta:
        model = Domain
        fields = ("domain", "is_primary")


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
            "created_at",
            "domains",
        )
        read_only_fields = ("schema_name", "created_at")
