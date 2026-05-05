from core.viewsets import TenantSafeModelViewSet

from .models import ContentItem
from .serializers import ContentItemSerializer


class ContentItemViewSet(TenantSafeModelViewSet):
    queryset = ContentItem.objects.all()
    serializer_class = ContentItemSerializer
    required_perm = "content:read"
