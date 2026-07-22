"""Messaging service — participant-scoped reads + participant resolution, wrapping the
preserved domain fns (create_thread / post_message / mark_read)."""

from __future__ import annotations

from django.db.models import QuerySet
from django.utils.translation import gettext_lazy as _

from apps.messaging.dto.thread_dto import CreateThreadDTO
from apps.messaging.interfaces.repositories import IThreadRepository
from apps.messaging.interfaces.services import IThreadService
from apps.messaging.models import Message, Thread
from apps.messaging.services import (
    create_thread,
    mark_read,
    post_message,
    set_notifications_muted,
)
from apps.users.models import User
from core.exceptions import PermissionException, ValidationException


class ThreadService(IThreadService):
    def __init__(self, repository: IThreadRepository) -> None:
        self.repository = repository

    def scoped_threads(self, *, user) -> QuerySet[Thread]:
        return self.repository.participant_threads(user=user)

    def get_thread(self, *, user, pk: int) -> Thread | None:
        return self.repository.get_participant_thread(user=user, pk=pk)

    def messages_of(self, *, thread: Thread) -> QuerySet[Message]:
        return self.repository.messages_of(thread=thread)

    def unread_counts(self, *, thread_ids: list[int], viewer_id: int) -> dict[int, int]:
        return self.repository.unread_counts(thread_ids=thread_ids, viewer_id=viewer_id)

    def contacts(self, *, user, category: str = "") -> QuerySet[User]:
        return self.repository.contacts_for(user=user, category=category)

    def create(self, data: CreateThreadDTO, *, creator) -> Thread:
        if self.repository.is_active_teacher(user=creator):
            requested_others = set(data.participant_ids) - {creator.pk}
            allowed = set(
                self.repository.contacts_for(user=creator)
                .filter(pk__in=requested_others)
                .values_list("pk", flat=True)
            )
            if allowed != requested_others:
                raise PermissionException(
                    _("One or more recipients are outside your messaging scope."),
                    code="recipient_out_of_scope",
                )
        users = self.repository.active_members(ids=data.participant_ids)
        if len(users) != len(data.participant_ids):
            raise ValidationException(
                _("One or more participants were not found."), code="unknown_participant"
            )
        return create_thread(
            creator=creator,
            participants=users,
            subject=data.subject,
            first_body=data.first_body,
            attachments=data.attachments,
        )

    def post(self, *, thread: Thread, sender, body: str, attachments: list) -> Message:
        return post_message(thread=thread, sender=sender, body=body, attachments=attachments)

    def mark_read(self, *, thread: Thread, user) -> None:
        mark_read(thread=thread, user=user)

    def set_notifications_muted(self, *, thread: Thread, user, muted: bool) -> None:
        set_notifications_muted(thread=thread, user=user, muted=muted)

    def presign_attachment(self, *, filename: str, content_type: str, size_bytes: int, requested_by) -> dict:
        from apps.messaging.services import presign_attachment_upload

        return presign_attachment_upload(
            filename=filename,
            content_type=content_type,
            size_bytes=size_bytes,
            requested_by=requested_by,
        )

    def attachment_download_url(self, *, thread: Thread, key: str) -> str:
        from apps.messaging.services import attachment_download_url

        return attachment_download_url(thread=thread, key=key)
