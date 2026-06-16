from __future__ import annotations

from rest_framework import serializers

from apps.content.models import (
    ContentLesson,
    ContentLibrary,
    Course,
    Folder,
    LessonFile,
    Module,
)


class ContentLibrarySerializer(serializers.ModelSerializer):
    class Meta:
        model = ContentLibrary
        fields = (
            "id",
            "name",
            "description",
            "visibility",
            "department",
            "cohort",
            "allowed_roles",
            "is_active",
        )


class CourseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Course
        fields = ("id", "library", "subject", "title", "description", "order")


class ModuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Module
        fields = ("id", "course", "title", "order")


class ContentLessonSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContentLesson
        fields = ("id", "module", "title", "description", "order")


class FolderSerializer(serializers.ModelSerializer):
    class Meta:
        model = Folder
        fields = ("id", "library", "parent", "name")


class LessonFileSerializer(serializers.ModelSerializer):
    class Meta:
        model = LessonFile
        fields = (
            "id",
            "lesson",
            "folder",
            "title",
            "content_type",
            "size_bytes",
            "status",
            "reject_reason",
            "version",
            "previous_version",
            "thumbnail_key",
            "view_count",
            "download_count",
            "created_at",
        )
        read_only_fields = fields


class ContentUploadUrlSerializer(serializers.Serializer):
    filename = serializers.CharField(max_length=255)
    content_type = serializers.CharField(max_length=127)
    size_bytes = serializers.IntegerField(min_value=1)
    lesson = serializers.PrimaryKeyRelatedField(
        queryset=ContentLesson.objects.all(), required=False, allow_null=True
    )
    folder = serializers.PrimaryKeyRelatedField(
        queryset=Folder.objects.all(), required=False, allow_null=True
    )
    title = serializers.CharField(max_length=255, required=False, allow_blank=True)

    def validate(self, attrs):
        if not attrs.get("lesson") and not attrs.get("folder"):
            raise serializers.ValidationError("A file must be attached to a lesson or a folder.")
        return attrs


class NewVersionSerializer(serializers.Serializer):
    filename = serializers.CharField(max_length=255)
    content_type = serializers.CharField(max_length=127)
    size_bytes = serializers.IntegerField(min_value=1)
