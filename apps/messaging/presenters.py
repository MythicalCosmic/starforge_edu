"""Messaging response presenters (the DRF Thread/Message serializer shape)."""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from apps.messaging.models import Message, Thread, ThreadParticipant
from core.permissions import Role


def participant_to_dict(participant: ThreadParticipant) -> dict:
    return {
        "user": participant.user_id,
        "last_read_at": participant.last_read_at.isoformat() if participant.last_read_at else None,
        "added_at": participant.added_at.isoformat(),
    }


def thread_to_dict(thread: Thread, *, unread_count: int) -> dict:
    # unread_count is supplied by the caller (computed in one bounded query via
    # ThreadService.unread_counts) rather than derived from a prefetch of every message.
    return {
        "id": thread.id,
        "subject": thread.subject,
        "branch": thread.branch_id,
        "created_by": thread.created_by_id,
        "last_message_at": thread.last_message_at.isoformat() if thread.last_message_at else None,
        "created_at": thread.created_at.isoformat(),
        "participants": [participant_to_dict(p) for p in thread.participants.all()],
        "unread_count": unread_count,
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


def contact_to_dict(user) -> dict:
    """Safe messaging recipient summary backed by a real bridge User id."""
    teacher = getattr(user, "teacher_profile", None)
    staff = getattr(user, "staff_profile", None)
    student = getattr(user, "student_profile", None)
    if getattr(user, "contact_is_staff", False) and teacher is not None and teacher.is_active:
        principal_kind, profile = "teacher", teacher
    elif getattr(user, "contact_is_staff", False) and staff is not None and staff.is_active:
        principal_kind, profile = "staff", staff
    else:
        principal_kind, profile = "student", student

    memberships = getattr(user, "messaging_memberships", ())

    def membership_matches(membership) -> bool:
        account_type = membership.account_type
        if account_type is not None:
            return account_type.account_kind == principal_kind
        if principal_kind == "teacher":
            return membership.role == Role.TEACHER
        if principal_kind == "student":
            return membership.role == Role.STUDENT
        return membership.role not in (Role.TEACHER, Role.STUDENT, Role.PARENT)

    membership = next((m for m in memberships if membership_matches(m)), None)
    if membership is None:
        membership = next(iter(memberships), None)
    if membership is not None and membership.account_type is not None:
        role_label = membership.account_type.name
        role_slug = membership.account_type.slug
    else:
        role_slug = membership.role if membership is not None else principal_kind
        role_label = role_slug.replace("_", " ").title()

    display_name = profile.get_full_name() if profile is not None else ""
    username = (profile.username if profile is not None else "") or user.username
    last_seen = user.last_seen_at
    return {
        # Keep `id` as a compatibility alias while making the bridge semantics explicit.
        "id": user.pk,
        "user_id": user.pk,
        "principal_kind": principal_kind,
        "category": "student" if principal_kind == "student" else "staff",
        "profile_id": profile.pk if profile is not None else None,
        "display_name": display_name or username,
        "username": username,
        "role_label": role_label,
        "role_slug": role_slug,
        "is_online": bool(
            last_seen and last_seen >= timezone.now() - timedelta(minutes=5)
        ),
    }
