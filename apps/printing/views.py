from core.viewsets import TenantSafeModelViewSet

from .models import PrintingItem
from .serializers import PrintingItemSerializer


class PrintingItemViewSet(TenantSafeModelViewSet):
    queryset = PrintingItem.objects.all()
    serializer_class = PrintingItemSerializer
    required_perm = "printing:read"
