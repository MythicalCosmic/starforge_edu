from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters

from core.viewsets import TenantSafeModelViewSet

from .models import Guardian, ParentProfile
from .serializers import GuardianSerializer, ParentProfileSerializer


class ParentProfileViewSet(TenantSafeModelViewSet):
    queryset = ParentProfile.objects.select_related("user").all()
    serializer_class = ParentProfileSerializer
    required_perm = "parents:read"

    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["user__phone", "user__email", "user__first_name", "user__last_name"]
    ordering_fields = ["created_at"]


class GuardianViewSet(TenantSafeModelViewSet):
    queryset = Guardian.objects.select_related("parent__user", "student__user").all()
    serializer_class = GuardianSerializer
    required_perm = "parents:read"

    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["student", "parent", "is_primary", "relationship"]
