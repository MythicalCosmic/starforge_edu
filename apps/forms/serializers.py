from __future__ import annotations

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.forms.models import Form, FormAnswer, FormField, FormResponse
from apps.org.models import Branch


class FormFieldSerializer(serializers.ModelSerializer):
    """Also used as the add-field input (id is read-only). A ModelSerializer here
    keeps `label`/`required`/`help_text` from shadowing the DRF Field base attrs."""

    class Meta:
        model = FormField
        fields = ("id", "label", "field_type", "required", "order", "options", "help_text")
        read_only_fields = ("id",)


class FormSerializer(serializers.ModelSerializer):
    # Named form_fields (not "fields") to avoid shadowing DRF's Serializer.fields.
    form_fields = FormFieldSerializer(source="fields", many=True, read_only=True)

    class Meta:
        model = Form
        fields = (
            "id",
            "title",
            "description",
            "status",
            "is_anonymous",
            "allow_multiple",
            "branch",
            "opens_at",
            "closes_at",
            "created_by",
            "published_at",
            "closed_at",
            "created_at",
            "form_fields",
        )
        read_only_fields = (
            "id",
            "status",
            "created_by",
            "published_at",
            "closed_at",
            "created_at",
            "form_fields",
        )


class FormCreateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    is_anonymous = serializers.BooleanField(required=False, default=False)
    allow_multiple = serializers.BooleanField(required=False, default=False)
    branch = serializers.PrimaryKeyRelatedField(
        queryset=Branch.objects.filter(archived_at__isnull=True), required=False, allow_null=True
    )
    opens_at = serializers.DateTimeField(required=False, allow_null=True)
    closes_at = serializers.DateTimeField(required=False, allow_null=True)


class FormUpdateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    is_anonymous = serializers.BooleanField(required=False)
    allow_multiple = serializers.BooleanField(required=False)
    opens_at = serializers.DateTimeField(required=False, allow_null=True)
    closes_at = serializers.DateTimeField(required=False, allow_null=True)


class SubmitResponseSerializer(serializers.Serializer):
    answers = serializers.JSONField()

    def validate_answers(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError(_("answers must be a list of {field, value} objects."))
        for item in value:
            if not isinstance(item, dict) or "field" not in item:
                raise serializers.ValidationError(_("each answer needs a 'field' id."))
        return value


class FormAnswerSerializer(serializers.ModelSerializer):
    class Meta:
        model = FormAnswer
        fields = ("field", "value")
        read_only_fields = fields


class FormResponseSerializer(serializers.ModelSerializer):
    answers = FormAnswerSerializer(many=True, read_only=True)

    class Meta:
        model = FormResponse
        fields = ("id", "form", "respondent", "created_at", "answers")
        read_only_fields = fields
