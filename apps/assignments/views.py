from core.viewsets import TenantSafeModelViewSet

from .models import AssignmentItem
from .serializers import AssignmentItemSerializer


class AssignmentItemViewSet(TenantSafeModelViewSet):
    queryset = AssignmentItem.objects.all()
    serializer_class = AssignmentItemSerializer
    resource = "assignments"
