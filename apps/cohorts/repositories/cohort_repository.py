"""ORM-backed cohort repository.

The list presenter renders each FK id (branch/department/primary_teacher/
default_room) together with a readable ``_name`` companion and the nested
``co_teachers``. ``select_related`` those four FK paths (JOINs, not extra queries)
and ``prefetch_related`` ``co_teachers`` so a page of N cohorts stays 2 queries,
not 1 + N.
"""

from __future__ import annotations

from django.db.models import Prefetch, QuerySet

from apps.cohorts.interfaces.repositories import ICohortRepository
from apps.cohorts.models import Cohort, CohortMembership, CohortTeacher
from apps.teachers.models import TeacherType
from core.repositories import BaseRepository


class CohortRepository(BaseRepository[Cohort], ICohortRepository):
    model = Cohort

    def get_queryset(self) -> QuerySet[Cohort]:
        return Cohort.objects.select_related(
            "branch", "department", "primary_teacher__user", "default_room"
        ).prefetch_related(
            Prefetch(
                "co_teachers",
                queryset=CohortTeacher.objects.select_related("teacher__user", "teacher_type").order_by(
                    "teacher_type__sort_order", "teacher__last_name", "id"
                ),
            )
        )

    def has_memberships(self, cohort: Cohort) -> bool:
        return cohort.memberships.exists()

    def active_members(self, cohort: Cohort) -> QuerySet[CohortMembership]:
        # `cohort` is join-loaded (alongside student__user) so membership_to_dict's
        # cohort_name/student_name add no query per row on the members list.
        return (
            CohortMembership.objects.filter(cohort=cohort, end_date__isnull=True)
            .select_related("student__user", "cohort")
            .order_by("student__user__last_name")
        )

    def teacher_types(self) -> QuerySet[TeacherType]:
        return TeacherType.objects.all().order_by("sort_order", "name", "id")

    def get_teacher_type(self, teacher_type_id: int) -> TeacherType | None:
        return TeacherType.objects.filter(pk=teacher_type_id).first()

    def teacher_assignments(self, cohort: Cohort) -> QuerySet[CohortTeacher]:
        return (
            CohortTeacher.objects.filter(cohort=cohort)
            .select_related("teacher__user", "teacher_type")
            .order_by("teacher_type__sort_order", "teacher__last_name", "id")
        )

    def get_teacher_assignment(self, cohort: Cohort, assignment_id: int) -> CohortTeacher | None:
        return self.teacher_assignments(cohort).filter(pk=assignment_id).first()
