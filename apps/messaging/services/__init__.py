"""Messaging services (F4-4).

Preserved verbatim; the layered service (services/v1/thread_service.py) wraps
`create_thread` / `post_message` / `mark_read` after the view validates the body and
resolves participants. `post_message` fans out realtime notifications via
apps.notifications.dispatch (pointers only, never the body).
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from pathlib import PurePosixPath

from botocore.exceptions import ClientError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.messaging.models import Message, MessageAttachmentUploadGrant, Thread, ThreadParticipant
from core.exceptions import NotFoundException, PermissionException, UnprocessableEntity, ValidationException
from core.permissions import Role
from core.utils import current_schema
from infrastructure.storage.s3_client import head_object, presign_download, presign_post_upload

_NON_STAFF = {Role.STUDENT, Role.PARENT}
_MAX_ATTACHMENTS = 10
_MAX_OTHER_PARTICIPANTS = 100


@transaction.atomic
def presign_attachment_upload(*, filename: str, content_type: str, size_bytes: int, requested_by) -> dict:
    """Create an exact-size upload policy and an owner-bound, single-use grant."""
    from apps.content.services import _EXT_MIME
    from apps.org.selectors import get_center_settings

    filename = PurePosixPath(filename.replace("\\", "/")).name.strip()
    if not filename or filename in {".", ".."} or len(filename) > 255:
        raise ValidationException(
            _("That filename is not allowed."),
            code="invalid_filename",
            fields={"filename": ["Provide a basename of at most 255 characters."]},
        )
    if size_bytes < 1:
        raise ValidationException(
            _("size_bytes must be positive."),
            code="validation_error",
            fields={"size_bytes": ["Must be at least 1."]},
        )
    content_type = content_type.strip().lower()
    if not content_type or len(content_type) > 127:
        raise ValidationException(
            _("A valid content type is required."),
            code="validation_error",
            fields={"content_type": ["Required; at most 127 characters."]},
        )

    settings_obj = get_center_settings()
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    allowed = {str(ext).lower().lstrip(".") for ext in settings_obj.allowed_file_types}
    if extension not in allowed:
        raise UnprocessableEntity(
            _("That file type is not allowed."),
            code="file_type_not_allowed",
            fields={"filename": [f"Extension '.{extension}' is not allowed."]},
        )
    expected_types = _EXT_MIME.get(extension)
    if expected_types is not None and content_type not in expected_types:
        raise UnprocessableEntity(
            _("The content type does not match the filename."),
            code="content_type_mismatch",
            fields={"content_type": [f"'{content_type}' is not valid for '.{extension}'."]},
        )
    max_bytes = settings_obj.max_upload_mb * 1024 * 1024
    if size_bytes > max_bytes:
        raise UnprocessableEntity(
            _("That file is too large."),
            code="file_too_large",
            fields={"size_bytes": [f"Exceeds the {settings_obj.max_upload_mb} MB limit."]},
        )

    key = f"{current_schema()}/messaging/{requested_by.pk}/{uuid.uuid4().hex}/{filename}"
    expires_at = timezone.now() + timedelta(minutes=10)
    grant = MessageAttachmentUploadGrant.objects.create(
        key=key,
        requested_by=requested_by,
        content_type=content_type,
        expected_size_bytes=size_bytes,
        expires_at=expires_at,
    )
    post = presign_post_upload(key, content_type=content_type, size_bytes=size_bytes)
    return {
        "url": post["url"],
        "fields": post["fields"],
        "method": "POST",
        "key": key,
        "grant_id": grant.pk,
        "expires_at": expires_at.isoformat(),
    }


def _verify_and_consume_attachment_grants(*, keys: list[str], actor) -> None:
    if not keys:
        return
    if not isinstance(keys, list) or any(not isinstance(key, str) for key in keys):
        raise ValidationException(
            _("Attachments must be a list of upload keys."),
            code="validation_error",
            fields={"attachments": ["Each attachment key must be text."]},
        )
    if len(keys) > _MAX_ATTACHMENTS or len(keys) != len(set(keys)):
        raise ValidationException(
            _("Attachments must be unique and limited to ten files."),
            code="validation_error",
            fields={"attachments": ["Provide at most 10 unique keys."]},
        )
    prefix = f"{current_schema()}/messaging/{actor.pk}/"
    if any(not isinstance(key, str) or not key.startswith(prefix) for key in keys):
        raise UnprocessableEntity(
            _("One or more attachment keys are not authorized."),
            code="invalid_attachment_key",
            fields={"attachments": ["Use keys returned by your messaging upload request."]},
        )

    now = timezone.now()
    grants = {
        grant.key: grant
        for grant in MessageAttachmentUploadGrant.objects.select_for_update().filter(
            key__in=keys,
            requested_by=actor,
            consumed_at__isnull=True,
            expires_at__gt=now,
        )
    }
    if set(grants) != set(keys):
        raise UnprocessableEntity(
            _("An attachment grant is missing, expired, used, or belongs to another user."),
            code="invalid_attachment_grant",
            fields={"attachments": ["Request a new upload URL and upload the file again."]},
        )

    for key in keys:
        grant = grants[key]
        try:
            metadata = head_object(key)
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code not in {"404", "NoSuchKey", "NotFound"}:
                raise
            raise UnprocessableEntity(
                _("The uploaded attachment could not be found."),
                code="attachment_not_uploaded",
                fields={"attachments": ["Upload the file before sending the message."]},
            ) from exc
        actual_size = int(metadata.get("ContentLength", -1))
        actual_type = str(metadata.get("ContentType", "")).split(";", 1)[0].strip().lower()
        if actual_size != grant.expected_size_bytes:
            raise UnprocessableEntity(
                _("The uploaded attachment has the wrong size."),
                code="attachment_size_mismatch",
                fields={"attachments": ["The stored size does not match the upload grant."]},
            )
        if actual_type != grant.content_type:
            raise UnprocessableEntity(
                _("The uploaded attachment has the wrong content type."),
                code="attachment_type_mismatch",
                fields={"attachments": ["The stored type does not match the upload grant."]},
            )
        grant.actual_size_bytes = actual_size
        grant.consumed_at = now
        grant.save(update_fields=["actual_size_bytes", "consumed_at"])


def attachment_download_url(*, thread: Thread, key: str) -> str:
    """Resolve a key only when it belongs to a message in the scoped thread."""
    if not key or len(key) > 512 or not key.startswith(f"{current_schema()}/messaging/"):
        raise NotFoundException(_("Attachment not found."), code="not_found")
    if not Message.objects.filter(thread=thread, attachments__contains=[key]).exists():
        raise NotFoundException(_("Attachment not found."), code="not_found")
    return presign_download(key, expires_in=300)


@transaction.atomic
def create_thread(
    *, creator, participants: list, subject: str = "", first_body: str = "", attachments=None
) -> Thread:
    """Open a thread between the creator and `participants` (User objects).

    Safeguarding (dignity DNA): a non-staff opener (student/parent) may only message
    STAFF — never another student/parent — so the channel can't be used for
    unsupervised student-to-student contact. Staff may message anyone.
    """
    members = list({creator.id: creator, **{u.id: u for u in participants}}.values())  # dedup, incl. creator
    others = [u for u in members if u.id != creator.id]
    if not others:
        raise ValidationException(
            _("A thread needs at least one other participant."), code="thread_needs_participant"
        )
    if len(others) > _MAX_OTHER_PARTICIPANTS:
        raise ValidationException(
            _("A thread has too many participants."),
            code="too_many_participants",
            fields={"participant_ids": ["At most 100 other participants are allowed."]},
        )
    # Resolve every role in one query. The former _roles_of(user) helper issued a
    # separate role-membership query for every participant, making a large create
    # request an avoidable N+1 database load.
    from apps.users.models import RoleMembership

    member_ids = [user.id for user in members]
    roles_by_user: dict[int, set[str]] = {user_id: set() for user_id in member_ids}
    creator_branch_id: int | None = None
    memberships = RoleMembership.objects.filter(user_id__in=member_ids, revoked_at__isnull=True).order_by(
        "-granted_at", "-id"
    )
    for user_id, role, branch_id in memberships.values_list("user_id", "role", "branch_id"):
        roles_by_user[user_id].add(role)
        if user_id == creator.id and creator_branch_id is None and branch_id is not None:
            creator_branch_id = branch_id

    def is_staff(user_id: int) -> bool:
        return bool(roles_by_user[user_id] - _NON_STAFF)

    # Safeguarding (dignity DNA) enforced on the resulting PARTICIPANT SET, not just
    # the opener's role: at most one student in any thread (no unsupervised peer
    # channel, even one opened by a teacher), and a non-staff opener may only reach
    # staff (a student/parent can't initiate contact with another non-staff person).
    if sum(1 for user in members if Role.STUDENT in roles_by_user[user.id]) > 1:
        raise PermissionException(
            _("A conversation can include at most one student."), code="non_staff_recipient"
        )
    if not is_staff(creator.id) and any(not is_staff(user.id) for user in others):
        raise PermissionException(_("You can only message staff."), code="non_staff_recipient")

    thread = Thread.objects.create(subject=subject, created_by=creator, branch_id=creator_branch_id)
    ThreadParticipant.objects.bulk_create([ThreadParticipant(thread=thread, user=u) for u in members])

    if first_body.strip() or attachments:
        post_message(thread=thread, sender=creator, body=first_body, attachments=attachments)
    return thread


@transaction.atomic
def post_message(*, thread: Thread, sender, body: str, attachments=None) -> Message:
    """Append a message. The sender must already be a participant. Bumps the thread,
    marks the sender caught-up, and notifies the other participants (realtime push
    reuses the notifications fan-out)."""
    attachments = [] if attachments is None else attachments
    if not body.strip() and not attachments:
        raise ValidationException(_("A message needs text or an attachment."), code="empty_message")
    if not ThreadParticipant.objects.filter(thread=thread, user=sender).exists():
        raise PermissionException(_("You are not a participant of this thread."), code="not_participant")
    _verify_and_consume_attachment_grants(keys=attachments, actor=sender)

    now = timezone.now()
    message = Message.objects.create(thread=thread, sender=sender, body=body, attachments=attachments)
    Thread.objects.filter(pk=thread.pk).update(last_message_at=now, updated_at=now)
    thread.last_message_at = now
    thread.updated_at = now
    # The sender has, by definition, read up to their own message.
    ThreadParticipant.objects.filter(thread=thread, user=sender).update(last_read_at=now)
    _notify_others(thread=thread, sender=sender, message=message)
    return message


def _notify_others(*, thread: Thread, sender, message: Message) -> None:
    from apps.notifications.services import dispatch

    recipient_ids = (
        ThreadParticipant.objects.filter(thread=thread).exclude(user=sender).values_list("user_id", flat=True)
    )
    # Privacy: the notification carries only pointers (thread/message/sender) — never
    # the message body. Content lives once, in the access-scoped thread, so it can't
    # leak through (or be stranded in) a recipient's notification feed.
    for uid in recipient_ids:
        dispatch(
            event_type="message.received",
            recipient_id=uid,
            context={
                "thread_id": thread.pk,
                "message_id": message.pk,
                "sender": sender.get_full_name() if sender else "",
            },
            dedupe_key=f"message:{message.pk}:{uid}",
        )


def mark_read(*, thread: Thread, user) -> None:
    ThreadParticipant.objects.filter(thread=thread, user=user).update(last_read_at=timezone.now())
