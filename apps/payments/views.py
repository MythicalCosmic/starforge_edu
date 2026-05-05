from core.viewsets import TenantSafeModelViewSet

from .models import PaymentItem
from .serializers import PaymentItemSerializer


class PaymentItemViewSet(TenantSafeModelViewSet):
    queryset = PaymentItem.objects.all()
    serializer_class = PaymentItemSerializer
    required_perm = "payments:read"
