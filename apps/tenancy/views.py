from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response

from . import services
from .models import Center
from .serializers import CenterSerializer, DomainCreateSerializer, DomainSerializer


class CenterViewSet(viewsets.ReadOnlyModelViewSet):
    """Public-schema platform API: list/inspect Centers + manage their domains.

    Mounted at /api/v1/platform/centers/. Platform-staff only — `IsAdminUser`
    is now functional thanks to TD-3 public-schema users. Center *creation* goes
    through `services.provision_center` (management command / control center).
    """

    queryset = Center.objects.prefetch_related("domains").all()
    serializer_class = CenterSerializer
    permission_classes = [IsAdminUser]

    @extend_schema(
        summary="List or add a Center's domains",
        request=DomainCreateSerializer,
        responses={200: DomainSerializer(many=True), 201: DomainSerializer},
        tags=["platform"],
    )
    @action(detail=True, methods=["get", "post"], url_path="domains")
    def domains(self, request, pk=None):
        center = self.get_object()
        if request.method == "POST":
            serializer = DomainCreateSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            domain = services.add_domain(
                center,
                domain=serializer.validated_data["domain"],
                is_primary=serializer.validated_data["is_primary"],
            )
            return Response(DomainSerializer(domain).data, status=status.HTTP_201_CREATED)
        return Response(DomainSerializer(center.domains.all(), many=True).data)

    @extend_schema(
        summary="Make one of a Center's domains primary",
        request=None,
        responses=DomainSerializer,
        tags=["platform"],
    )
    @action(
        detail=True,
        methods=["post"],
        url_path=r"domains/(?P<domain_id>[^/.]+)/set-primary",
    )
    def set_primary(self, request, pk=None, domain_id=None):
        center = self.get_object()
        domain = services.set_primary_domain(center, int(domain_id))
        return Response(DomainSerializer(domain).data)
