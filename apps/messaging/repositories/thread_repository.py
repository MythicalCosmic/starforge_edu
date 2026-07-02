"""ORM-backed messaging repository — participant-scoped thread reads."""

from __future__ import annotations

from django.db.models import Exists, OuterRef, QuerySet

from apps.messaging.interfaces.repositories import IThreadRepository
from apps.messaging.models import Message, Thread
from apps.users.models import RoleMembership, User
from core.repositories import BaseRepository


class ThreadRepository(BaseRepository[Thread], IThreadRepository):
    model = Thread

    def participant_threads(self, *, user) -> QuerySet[Thread]:
        # Strict isolation: only threads the user is a member of are ever resolvable,
        # so every detail/action is participant-gated by construction.
        return (
            Thread.objects.filter(participants__user_id=user.pk)
            .distinct()
            .select_related("branch", "created_by")
            .prefetch_related("participants", "messages")
        )

    def get_participant_thread(self, *, user, pk: int) -> Thread | None:
        return self.participant_threads(user=user).filter(pk=pk).first()

    def messages_of(self, *, thread: Thread) -> QuerySet[Message]:
        return Message.objects.filter(thread=thread).select_related("sender")

    def active_members(self, *, ids: list[int]) -> list[User]:
        # Participants must be active members of THIS center — never a membership-less /
        # cross-tenant user row. Exists() (not a role_memberships__isnull filter, which a
        # LEFT JOIN would let membership-less users slip through).
        active_member = RoleMembership.objects.filter(user_id=OuterRef("pk"), revoked_at__isnull=True)
        return list(User.objects.filter(id__in=ids, is_active=True).filter(Exists(active_member)))
