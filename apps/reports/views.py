from core.viewsets import TenantSafeModelViewSet

from .models import ReportItem
from .serializers import ReportItemSerializer


class ReportItemViewSet(TenantSafeModelViewSet):
    queryset = ReportItem.objects.all()
    serializer_class = ReportItemSerializer
    resource = "reports"
