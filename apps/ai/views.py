from core.viewsets import TenantSafeModelViewSet

from .models import AiItem
from .serializers import AiItemSerializer


class AiItemViewSet(TenantSafeModelViewSet):
    queryset = AiItem.objects.all()
    serializer_class = AiItemSerializer
    resource = "ai_app"
