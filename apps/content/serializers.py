from __future__ import annotations

import re
from typing import cast

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.content.models import (
    ContentLesson,
    ContentLibrary,
    Course,
    Folder,
    LessonFile,
    Module,
)

# The client filename flows verbatim into the S3 key ({schema}/tmp/{uuid}/{name}
# and later {schema}/content/{id}/{name}). A name with '/', '\', '..', NUL or a
# leading dot/slash produces an ambiguous/dangerous key that can escape the
# per-upload {uuid}/ isolation (and confuse the extension allowlist check). We
# REJECT such names outright (not silently rewrite them) so the client gets a
# clear 400 and only an allowlisted basename ever reaches the key.
_FILENAME_ALLOWED = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]{0,254}$")


def _sanitize_filename(value: str) -> str:
    """Reject a client filename that is not a safe basename.

    Stricter twin of apps/assignments/services.validate_and_presign_upload:
    path separators ('/' or '\\'), '..', NUL, a leading dot/slash, or any char
    outside [A-Za-z0-9._-] raise ValidationError (a 400) instead of being
    normalized, so the value is always safe to interpolate into an S3 key.
    """
    name = (value or "").strip()
    if not name or name in {".", ".."} or name.startswith("."):
        raise serializers.ValidationError(
            _("Filename must be a non-empty basename without path separators or a leading dot.")
        )
    if not _FILENAME_ALLOWED.match(name):
        raise serializers.ValidationError(
            _("Filename may only contain letters, digits, '.', '_' and '-' (no path separators).")
        )
    return name


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
    # Never expose the raw schema-prefixed S3 key; hand out a TTL-limited signed
    # URL instead (mirrors the download-url flow). None when no thumbnail exists.
    thumbnail_url = serializers.SerializerMethodField()

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
            "thumbnail_url",
            "view_count",
            "download_count",
            "created_at",
        )
        read_only_fields = fields

    def get_thumbnail_url(self, obj: LessonFile) -> str | None:
        if not obj.thumbnail_key:
            return None
        from infrastructure.storage.s3_client import presign_download

        return presign_download(obj.thumbnail_key, expires_in=300)


class ContentUploadUrlSerializer(serializers.Serializer):
    filename = serializers.CharField(max_length=255)
    content_type = serializers.CharField(max_length=127)
    size_bytes = serializers.IntegerField(min_value=1)
    lesson = serializers.PrimaryKeyRelatedField(
        queryset=ContentLesson.objects.none(), required=False, allow_null=True
    )
    folder = serializers.PrimaryKeyRelatedField(
        queryset=Folder.objects.none(), required=False, allow_null=True
    )
    title = serializers.CharField(max_length=255, required=False, allow_blank=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Writes are scoped like reads: a writer may only attach files into a
        # lesson/folder whose library they can see (scoped_libraries). Otherwise
        # an out-of-scope PK 404s here, closing the scoped-reads/unscoped-writes
        # asymmetry. None context (e.g. schema gen) → empty queryset (fail-closed).
        from apps.content.selectors import scoped_libraries
        from core.permissions import get_user_roles

        request = self.context.get("request")
        if request is not None and getattr(request, "user", None) is not None:
            libs = scoped_libraries(user=request.user, roles=get_user_roles(request))
            lesson_field = cast(serializers.PrimaryKeyRelatedField, self.fields["lesson"])
            folder_field = cast(serializers.PrimaryKeyRelatedField, self.fields["folder"])
            lesson_field.queryset = ContentLesson.objects.filter(module__course__library__in=libs)
            folder_field.queryset = Folder.objects.filter(library__in=libs)

    def validate_filename(self, value: str) -> str:
        return _sanitize_filename(value)

    def validate(self, attrs):
        if not attrs.get("lesson") and not attrs.get("folder"):
            raise serializers.ValidationError(_("A file must be attached to a lesson or a folder."))
        return attrs


class NewVersionSerializer(serializers.Serializer):
    filename = serializers.CharField(max_length=255)
    content_type = serializers.CharField(max_length=127)
    size_bytes = serializers.IntegerField(min_value=1)

    def validate_filename(self, value: str) -> str:
        return _sanitize_filename(value)
