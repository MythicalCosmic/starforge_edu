"""ORM-backed messaging repository — participant-scoped thread reads."""

from __future__ import annotations

from django.db.models import Count, Exists, F, OuterRef, Prefetch, Q, QuerySet, Subquery

from apps.access.models import AccountType
from apps.cohorts.selectors import taught_cohorts
from apps.messaging.interfaces.repositories import IThreadRepository
from apps.messaging.models import Message, Thread, ThreadParticipant
from apps.students.models import StudentProfile
from apps.teachers.models import TeacherProfile
from apps.users.models import RoleMembership, User
from core.permissions import Role
from core.repositories import BaseRepository

_NON_STAFF_ROLES = {Role.STUDENT, Role.PARENT}
_MANAGEMENT_ROLES = {Role.DIRECTOR, Role.HEAD_OF_DEPT}
_LEGACY_STAFF_TEACHER_ROLES = tuple(role for role in Role.ALL if role not in _NON_STAFF_ROLES)
_MANAGEMENT_ACCOUNT_TYPE_SLUG = (
    Q(account_type__slug__icontains="ceo")
    | Q(account_type__slug__icontains="owner")
    | Q(account_type__slug__icontains="director")
    | Q(account_type__slug__icontains="manager")
    | Q(account_type__slug__icontains="head_of_dept")
    | Q(account_type__slug__icontains="head-of-dept")
    | Q(account_type__slug__iregex=r"(^|[-_])hod($|[-_])")
)


class ThreadRepository(BaseRepository[Thread], IThreadRepository):
    model = Thread

    def participant_threads(self, *, user) -> QuerySet[Thread]:
        # Strict isolation: only threads the user is a member of are ever resolvable,
        # so every detail/action is participant-gated by construction. `messages` is NOT
        # prefetched: it is append-only/unbounded and was only used to count unread — a
        # page of long threads would load tens of thousands of message rows just to produce
        # a few integers. Unread is now one bounded query (unread_counts). `participants` is
        # small and stays prefetched (the presenter emits the roster).
        return (
            Thread.objects.filter(participants__user_id=user.pk)
            .distinct()
            .select_related("branch", "created_by")
            .prefetch_related("participants")
        )

    def unread_counts(self, *, thread_ids: list[int], viewer_id: int) -> dict[int, int]:
        """{thread_id: unread_count} for `viewer_id` across the given threads in ONE query.

        Unread = messages from OTHERS newer than the viewer's own last_read for that thread
        (a null last_read means everything from others is unread) — the exact semantics the
        old per-row Python count had, but bounded to the page's threads and served by the
        Message(thread, created_at) index instead of loading every message row."""
        if not thread_ids:
            return {}
        viewer_last_read = ThreadParticipant.objects.filter(
            thread_id=OuterRef("thread_id"), user_id=viewer_id
        ).values("last_read_at")[:1]
        rows = (
            Message.objects.filter(thread_id__in=thread_ids)
            .exclude(sender_id=viewer_id)
            .annotate(_viewer_last_read=Subquery(viewer_last_read))
            .filter(Q(_viewer_last_read__isnull=True) | Q(created_at__gt=F("_viewer_last_read")))
            .values("thread_id")
            .annotate(n=Count("id"))
        )
        return {row["thread_id"]: row["n"] for row in rows}

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

    def is_active_teacher(self, *, user) -> bool:
        """Whether this bridge principal belongs to an active role-native teacher."""
        return TeacherProfile.objects.filter(user=user, is_active=True).exists()

    def contacts_for(self, *, user, category: str = "") -> QuerySet[User]:
        """Purpose-limited messaging directory.

        Every returned primary key is a real ``users.User`` bridge id accepted by
        thread creation. Staff/teacher contacts are active role-native accounts.
        An active teacher additionally sees only students in cohorts they actually
        teach, never the broader branch/department student directory.
        """
        active_staff_membership = RoleMembership.objects.filter(
            user_id=OuterRef("pk"), revoked_at__isnull=True
        ).filter(
            Q(
                account_type__is_active=True,
                account_type__account_kind__in=(
                    AccountType.AccountKind.STAFF,
                    AccountType.AccountKind.TEACHER,
                ),
            )
            | Q(account_type__isnull=True, role__in=_LEGACY_STAFF_TEACHER_ROLES)
        )
        active_student_membership = RoleMembership.objects.filter(
            user_id=OuterRef("pk"), revoked_at__isnull=True
        ).filter(
            Q(
                account_type__is_active=True,
                account_type__account_kind=AccountType.AccountKind.STUDENT,
            )
            | Q(account_type__isnull=True, role=Role.STUDENT)
        )
        management_membership = RoleMembership.objects.filter(
            user_id=OuterRef("pk"), revoked_at__isnull=True
        ).filter(
            (Q(account_type__is_active=True) & _MANAGEMENT_ACCOUNT_TYPE_SLUG)
            | Q(account_type__isnull=True, role__in=_MANAGEMENT_ROLES)
        )

        qs = (
            User.objects.filter(is_active=True)
            .exclude(pk=user.pk)
            .annotate(
                contact_is_staff=Exists(active_staff_membership),
                contact_is_student=Exists(active_student_membership),
                contact_is_management=Exists(management_membership),
            )
            .select_related("staff_profile", "teacher_profile", "student_profile")
        )

        staff_visible = Q(contact_is_staff=True, contact_is_management=False) & (
            Q(staff_profile__is_active=True) | Q(teacher_profile__is_active=True)
        )
        student_visible = Q(pk__in=[])
        if self.is_active_teacher(user=user):
            owned_student_ids = StudentProfile.objects.filter(
                user__is_active=True,
                is_active=True,
                status__in=(StudentProfile.Status.ENROLLED, StudentProfile.Status.ACTIVE),
                current_cohort__in=taught_cohorts(user=user),
            ).values("user_id")
            student_visible = Q(contact_is_student=True, pk__in=owned_student_ids)

        if category == "staff":
            visible = staff_visible
        elif category == "student":
            visible = student_visible
        else:
            visible = staff_visible | student_visible

        active_memberships = (
            RoleMembership.objects.filter(revoked_at__isnull=True)
            .filter(Q(account_type__isnull=True) | Q(account_type__is_active=True))
            .select_related("account_type")
            .order_by("-granted_at", "-id")
        )
        return (
            qs.filter(visible)
            .prefetch_related(
                Prefetch(
                    "role_memberships",
                    queryset=active_memberships,
                    to_attr="messaging_memberships",
                )
            )
            .order_by("id")
        )
