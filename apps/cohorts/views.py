from django.db.models import Count, Q
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters

from core.viewsets import TenantSafeModelViewSet

from .models import Cohort, CohortMembership, CohortTeacher
from .serializers import CohortMembershipSerializer, CohortSerializer, CohortTeacherSerializer


class CohortViewSet(TenantSafeModelViewSet):
    serializer_class = CohortSerializer
    required_perm = "cohorts:read"
    object_scope = "branch"

    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["branch", "department", "is_archived", "primary_teacher"]
    search_fields = ["name", "level"]
    ordering_fields = ["created_at", "name", "start_date"]

    def get_queryset(self):
        return (
            Cohort.objects.select_related("branch", "department", "primary_teacher")
            .annotate(student_count=Count("memberships", filter=Q(memberships__is_active=True)))
            .all()
        )


class CohortMembershipViewSet(TenantSafeModelViewSet):
    queryset = CohortMembership.objects.select_related("cohort", "student").all()
    serializer_class = CohortMembershipSerializer
    required_perm = "cohorts:read"

    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["cohort", "student", "is_active"]


class CohortTeacherViewSet(TenantSafeModelViewSet):
    queryset = CohortTeacher.objects.select_related("cohort", "teacher").all()
    serializer_class = CohortTeacherSerializer
    required_perm = "cohorts:read"

    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["cohort", "teacher"]
