from core.viewsets import TenantSafeModelViewSet

from .models import NotificationItem
from .serializers import NotificationItemSerializer


class NotificationItemViewSet(TenantSafeModelViewSet):
    queryset = NotificationItem.objects.all()
    serializer_class = NotificationItemSerializer
    required_perm = "notifications:read"
