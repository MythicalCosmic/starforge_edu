from core.viewsets import TenantSafeModelViewSet

from .models import ParentItem
from .serializers import ParentItemSerializer


class ParentItemViewSet(TenantSafeModelViewSet):
    queryset = ParentItem.objects.all()
    serializer_class = ParentItemSerializer
    required_perm = "parents:read"
