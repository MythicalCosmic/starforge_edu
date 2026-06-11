from core.viewsets import TenantSafeModelViewSet

from .models import AuditItem
from .serializers import AuditItemSerializer


class AuditItemViewSet(TenantSafeModelViewSet):
    queryset = AuditItem.objects.all()
    serializer_class = AuditItemSerializer
    resource = "audit"
