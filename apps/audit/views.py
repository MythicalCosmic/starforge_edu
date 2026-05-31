from django.db import connection
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, mixins, viewsets

from core.exceptions import TenantContextMissing
from core.pagination import TimelinePagination
from core.permissions import RolePermission

from .models import AuditLog
from .serializers import AuditLogSerializer


class AuditLogViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Read-only access to the append-only audit trail.

    Not a TenantSafeModelViewSet because the log must never be written through
    the API — rows come only from signals / audit_log(). We still enforce the
    tenant guard and the audit:read permission.
    """

    queryset = AuditLog.objects.all()
    serializer_class = AuditLogSerializer
    permission_classes = [RolePermission]
    required_perm = "audit:read"
    pagination_class = TimelinePagination

    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["action", "resource_type", "actor"]
    search_fields = ["resource_type", "resource_id", "user_agent"]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        schema = getattr(connection, "schema_name", None)
        public = getattr(connection, "get_public_schema_name", lambda: "public")()
        if not schema or schema == public:
            raise TenantContextMissing("This endpoint requires a tenant subdomain.")
