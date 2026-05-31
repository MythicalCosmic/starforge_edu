from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters

from core.viewsets import TenantSafeModelViewSet

from .models import StudentProfile
from .serializers import StudentProfileSerializer
from .services import generate_student_id


class StudentProfileViewSet(TenantSafeModelViewSet):
    queryset = StudentProfile.objects.select_related("user", "branch").all()
    serializer_class = StudentProfileSerializer
    required_perm = "students:read"
    object_scope = "branch"

    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["status", "branch"]
    search_fields = [
        "student_id",
        "user__phone",
        "user__email",
        "user__first_name",
        "user__last_name",
    ]
    ordering_fields = ["created_at", "student_id"]

    def perform_create(self, serializer):
        serializer.save(student_id=generate_student_id())
