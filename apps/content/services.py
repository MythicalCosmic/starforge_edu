"""Content storage services (TASKS §13, §23, TD-13/16).

The canonical signed-URL flow: `request_upload` (validate vs knobs → pending
`LessonFile` + presigned PUT) → client PUTs → `confirm_upload` (enqueue) →
`validate_uploaded_file` (libmagic sniff → clean/rejected, move tmp→content) →
`generate_thumbnail`. Downloads are presigned + counter-tracked. No S3 HTTP runs
in a request handler — only local URL signing (DoD #9).
"""

from __future__ import annotations

import io
import uuid

from django.db import transaction
from django.db.models import F
from django.utils.translation import gettext_lazy as _

from apps.content.models import FileView, LessonFile
from apps.org.selectors import get_center_settings
from core.exceptions import ConflictException, UnprocessableEntity
from core.utils import current_schema
from infrastructure.storage.s3_client import (
    copy_object,
    delete_object,
    download_bytes,
    get_object_range,
    head_object,
    presign_download,
    presign_upload,
    upload_bytes,
)

# Declared content-type must be consistent with the extension for known types.
_EXT_MIME: dict[str, set[str]] = {
    "pdf": {"application/pdf"},
    "mp4": {"video/mp4"},
    "pptx": {"application/vnd.openxmlformats-officedocument.presentationml.presentation"},
    "docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    "mp3": {"audio/mpeg"},
    "jpg": {"image/jpeg"},
    "jpeg": {"image/jpeg"},
    "png": {"image/png"},
    "webp": {"image/webp"},
}
_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
_THUMB_MAX_EDGE = 320


# ---------------------------------------------------------------------------
# Upload request (validate + presign)
# ---------------------------------------------------------------------------


def _validate_upload_inputs(*, filename: str, content_type: str, size_bytes: int, settings) -> None:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in {e.lower() for e in settings.allowed_file_types}:
        raise UnprocessableEntity(
            _("That file type is not allowed."),
            code="file_type_not_allowed",
            fields={"filename": [f"Extension '.{ext}' is not allowed."]},
        )
    expected = _EXT_MIME.get(ext)
    if expected is not None and content_type not in expected:
        raise UnprocessableEntity(
            _("The declared content type does not match the file extension."),
            code="file_type_not_allowed",
            fields={"content_type": [f"'{content_type}' is not valid for '.{ext}'."]},
        )
    if size_bytes > settings.max_upload_mb * 1024 * 1024:
        raise UnprocessableEntity(
            _("That file is too large."),
            code="file_too_large",
            fields={"size_bytes": [f"Exceeds the {settings.max_upload_mb} MB limit."]},
        )
    if settings.storage_quota_gb is not None:
        from apps.content.selectors import storage_used_bytes

        quota_bytes = settings.storage_quota_gb * 1024 * 1024 * 1024
        if storage_used_bytes() + size_bytes > quota_bytes:
            raise UnprocessableEntity(
                _("This center has reached its storage quota."), code="storage_quota_exceeded"
            )


@transaction.atomic
def request_upload(
    *, filename, content_type, size_bytes, user=None, lesson=None, folder=None, title=None, previous=None
) -> dict:
    """Validate against the knobs and create a `pending` LessonFile with a tmp
    key + presigned PUT URL. `previous` links a new version."""
    settings = get_center_settings()
    _validate_upload_inputs(
        filename=filename, content_type=content_type, size_bytes=size_bytes, settings=settings
    )
    if lesson is None and folder is None and previous is not None:
        lesson, folder = previous.lesson, previous.folder

    schema = current_schema()
    s3_key = f"{schema}/tmp/{uuid.uuid4().hex}/{filename}"
    lesson_file = LessonFile.objects.create(
        lesson=lesson,
        folder=folder,
        title=title or filename,
        s3_key=s3_key,
        content_type=content_type,
        size_bytes=size_bytes,
        status=LessonFile.Status.PENDING,
        version=(previous.version + 1) if previous else 1,
        previous_version=previous,
        uploaded_by=user,
    )
    expires_in = 600
    url = presign_upload(s3_key, expires_in=expires_in, content_type=content_type)
    return {"file": lesson_file, "url": url, "key": s3_key, "expires_in": expires_in}


@transaction.atomic
def confirm_upload(*, file: LessonFile) -> LessonFile:
    """Mark a pending upload ready and enqueue async validation. 409 if not
    pending. No S3 call here — just enqueue."""
    if file.status != LessonFile.Status.PENDING:
        raise ConflictException(_("This file has already been processed."), code="file_not_pending")
    schema = current_schema()
    transaction.on_commit(lambda: _enqueue_validate(file.pk, schema))
    return file


def _enqueue_validate(file_id: int, schema: str) -> None:
    from celery_tasks.content_tasks import validate_uploaded_file

    validate_uploaded_file.delay(file_id, _schema_name=schema)


# ---------------------------------------------------------------------------
# Async validation + thumbnailing (task bodies)
# ---------------------------------------------------------------------------


def _sniff_mime(buffer: bytes) -> str:
    """libmagic MIME sniff. Imported lazily so the app loads where libmagic's
    native lib is absent (e.g. a Windows dev box); CI/Linux runs it for real and
    unit tests monkeypatch this function."""
    import magic

    return magic.from_buffer(buffer, mime=True)


def _filename_of(s3_key: str) -> str:
    return s3_key.rsplit("/", 1)[-1]


def validate_uploaded_file(file_id: int) -> str:
    """Task body: sniff the uploaded object, reject on mismatch/oversize, else
    move tmp→content and mark clean (enqueuing a thumbnail for images).
    Idempotent: a non-pending file short-circuits. Runs under the tenant schema."""
    file = LessonFile.objects.get(pk=file_id)
    if file.status != LessonFile.Status.PENDING:
        return file.status

    head = head_object(file.s3_key)
    actual_size = int(head.get("ContentLength", file.size_bytes))
    settings = get_center_settings()
    if actual_size > settings.max_upload_mb * 1024 * 1024:
        return _reject(file, "Uploaded object exceeds the size limit.")
    file.size_bytes = actual_size

    sniffed = _sniff_mime(get_object_range(file.s3_key, start=0, end=8191))
    if sniffed.split("/")[0] != file.content_type.split("/")[0]:
        return _reject(file, f"Content sniff '{sniffed}' does not match declared '{file.content_type}'.")

    filename = _filename_of(file.s3_key)
    final_key = f"{current_schema()}/content/{file.pk}/{filename}"
    copy_object(src_key=file.s3_key, dest_key=final_key)
    delete_object(file.s3_key)

    file.s3_key = final_key
    file.status = LessonFile.Status.CLEAN
    file.save(update_fields=["s3_key", "size_bytes", "status", "updated_at"])

    if file.content_type in _IMAGE_TYPES:
        schema = current_schema()
        transaction.on_commit(lambda: _enqueue_thumbnail(file.pk, schema))
    return file.status


def _reject(file: LessonFile, reason: str) -> str:
    file.status = LessonFile.Status.REJECTED
    file.reject_reason = reason[:255]
    file.save(update_fields=["status", "reject_reason", "size_bytes", "updated_at"])
    return file.status


def _enqueue_thumbnail(file_id: int, schema: str) -> None:
    from celery_tasks.content_tasks import generate_thumbnail

    generate_thumbnail.delay(file_id, _schema_name=schema)


def generate_thumbnail(file_id: int) -> str | None:
    """Task body: render a ≤320px JPEG thumbnail for a clean image file.
    Idempotent: re-run short-circuits once `thumbnail_key` is set."""
    from PIL import Image

    file = LessonFile.objects.get(pk=file_id)
    if file.status != LessonFile.Status.CLEAN or file.content_type not in _IMAGE_TYPES:
        return None
    if file.thumbnail_key:
        return file.thumbnail_key

    raw = download_bytes(file.s3_key)
    image = Image.open(io.BytesIO(raw))
    image.thumbnail((_THUMB_MAX_EDGE, _THUMB_MAX_EDGE))
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG")

    thumb_key = f"{current_schema()}/content/{file.pk}/thumb.jpg"
    upload_bytes(thumb_key, buffer.getvalue(), content_type="image/jpeg")
    file.thumbnail_key = thumb_key
    file.save(update_fields=["thumbnail_key", "updated_at"])
    return thumb_key


# ---------------------------------------------------------------------------
# Download + view tracking
# ---------------------------------------------------------------------------


def download_url(*, file: LessonFile, user) -> dict:
    """Signed GET (TTL 300) for a CLEAN file; F()-increments download_count and
    records a FileView. Visibility is already enforced by the scoped queryset."""
    if file.status != LessonFile.Status.CLEAN:
        raise ConflictException(_("This file is not available for download."), code="file_not_clean")
    LessonFile.objects.filter(pk=file.pk).update(download_count=F("download_count") + 1)
    FileView.objects.create(file=file, user=user, action=FileView.Action.DOWNLOAD)
    return {"url": presign_download(file.s3_key, expires_in=300), "expires_in": 300}


def track_view(*, file: LessonFile, user) -> None:
    LessonFile.objects.filter(pk=file.pk).update(view_count=F("view_count") + 1)
    FileView.objects.create(file=file, user=user, action=FileView.Action.VIEW)


# ---------------------------------------------------------------------------
# Versioning
# ---------------------------------------------------------------------------


def create_new_version(*, previous: LessonFile, filename, content_type, size_bytes, user=None) -> dict:
    return request_upload(
        filename=filename,
        content_type=content_type,
        size_bytes=size_bytes,
        user=user,
        previous=previous,
    )
