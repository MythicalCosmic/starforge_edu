from core.viewsets import TenantSafeModelViewSet

from .models import AttendanceItem
from .serializers import AttendanceItemSerializer


class AttendanceItemViewSet(TenantSafeModelViewSet):
    queryset = AttendanceItem.objects.all()
    serializer_class = AttendanceItemSerializer
    required_perm = "attendance:read"
