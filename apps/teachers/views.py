from core.viewsets import TenantSafeModelViewSet

from .models import TeacherItem
from .serializers import TeacherItemSerializer


class TeacherItemViewSet(TenantSafeModelViewSet):
    queryset = TeacherItem.objects.all()
    serializer_class = TeacherItemSerializer
    required_perm = "teachers:read"
