from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters

from core.viewsets import TenantSafeModelViewSet

from .models import TeacherProfile
from .serializers import TeacherProfileSerializer


class TeacherProfileViewSet(TenantSafeModelViewSet):
    queryset = TeacherProfile.objects.select_related("user", "department").all()
    serializer_class = TeacherProfileSerializer
    required_perm = "teachers:read"

    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["department", "employment_type", "is_active"]
    search_fields = ["user__phone", "user__email", "user__first_name", "user__last_name"]
    ordering_fields = ["created_at", "hire_date"]
