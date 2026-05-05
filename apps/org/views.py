from core.viewsets import TenantSafeModelViewSet

from .models import Branch, Department
from .serializers import BranchSerializer, DepartmentSerializer


class BranchViewSet(TenantSafeModelViewSet):
    queryset = Branch.objects.all()
    serializer_class = BranchSerializer
    required_perm = "org:read"


class DepartmentViewSet(TenantSafeModelViewSet):
    queryset = Department.objects.select_related("branch")
    serializer_class = DepartmentSerializer
    required_perm = "org:read"
    object_scope = "branch"
