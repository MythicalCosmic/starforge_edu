from core.viewsets import TenantSafeModelViewSet

from .models import ScheduleItem
from .serializers import ScheduleItemSerializer


class ScheduleItemViewSet(TenantSafeModelViewSet):
    queryset = ScheduleItem.objects.all()
    serializer_class = ScheduleItemSerializer
    required_perm = "schedule:read"
