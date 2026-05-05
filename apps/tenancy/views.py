from rest_framework import viewsets
from rest_framework.permissions import IsAdminUser

from .models import Center
from .serializers import CenterSerializer


class CenterViewSet(viewsets.ReadOnlyModelViewSet):
    """Public-schema endpoint: list/inspect existing centers.

    Mounted at /api/v1/platform/centers/. Restricted to platform admins.
    Center *creation* should go through services.provision_center, called
    from a management command or a separate provisioning workflow.
    """

    queryset = Center.objects.all()
    serializer_class = CenterSerializer
    permission_classes = [IsAdminUser]
