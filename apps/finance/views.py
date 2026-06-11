from core.viewsets import TenantSafeModelViewSet

from .models import FinanceItem
from .serializers import FinanceItemSerializer


class FinanceItemViewSet(TenantSafeModelViewSet):
    queryset = FinanceItem.objects.all()
    serializer_class = FinanceItemSerializer
    resource = "finance"
