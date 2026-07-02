"""Messaging response presenters (the DRF Thread/Message serializer shape)."""

from __future__ import annotations

from apps.messaging.models import Message, Thread, ThreadParticipant


def participant_to_dict(participant: ThreadParticipant) -> dict:
    return {
        "user": participant.user_id,
        "last_read_at": participant.last_read_at.isoformat() if participant.last_read_at else None,
        "added_at": participant.added_at.isoformat(),
    }


def _unread_count(thread: Thread, viewer_id: int) -> int:
    part = next((p for p in thread.participants.all() if p.user_id == viewer_id), None)
    last_read = part.last_read_at if part else None
    # Messages from others, newer than the viewer's last read.
    return sum(
        1
        for m in thread.messages.all()
        if m.sender_id != viewer_id and (last_read is None or m.created_at > last_read)
    )


def thread_to_dict(thread: Thread, *, viewer_id: int) -> dict:
    return {
        "id": thread.id,
        "subject": thread.subject,
        "branch": thread.branch_id,
        "created_by": thread.created_by_id,
        "last_message_at": thread.last_message_at.isoformat() if thread.last_message_at else None,
        "created_at": thread.created_at.isoformat(),
        "participants": [participant_to_dict(p) for p in thread.participants.all()],
        "unread_count": _unread_count(thread, viewer_id),
    }


def message_to_dict(message: Message) -> dict:
    return {
        "id": message.id,
        "thread": message.thread_id,
        "sender": message.sender_id,
        "body": message.body,
        "attachments": message.attachments,
        "created_at": message.created_at.isoformat(),
    }
