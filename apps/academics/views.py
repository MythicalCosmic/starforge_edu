from core.viewsets import TenantSafeModelViewSet

from .models import AcademicItem
from .serializers import AcademicItemSerializer


class AcademicItemViewSet(TenantSafeModelViewSet):
    queryset = AcademicItem.objects.all()
    serializer_class = AcademicItemSerializer
    resource = "academics"
