from core.viewsets import TenantSafeModelViewSet

from .models import CohortItem
from .serializers import CohortItemSerializer


class CohortItemViewSet(TenantSafeModelViewSet):
    queryset = CohortItem.objects.all()
    serializer_class = CohortItemSerializer
    required_perm = "cohorts:read"
