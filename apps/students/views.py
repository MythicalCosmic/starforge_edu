from core.viewsets import TenantSafeModelViewSet

from .models import StudentItem
from .serializers import StudentItemSerializer


class StudentItemViewSet(TenantSafeModelViewSet):
    queryset = StudentItem.objects.all()
    serializer_class = StudentItemSerializer
    required_perm = "students:read"
