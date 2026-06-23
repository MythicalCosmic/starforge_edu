from django.urls import path
from rest_framework.routers import DefaultRouter

from apps.access.views import (
    EffectiveRolesView,
    PermissionCatalogView,
    RolePermissionOverrideViewSet,
)

router = DefaultRouter()
router.register("overrides", RolePermissionOverrideViewSet, basename="access-overrides")

# Read views precede the router (distinct paths, but keep them explicit + first).
urlpatterns = [
    path("roles/", EffectiveRolesView.as_view(), name="access-roles"),
    path("permissions/", PermissionCatalogView.as_view(), name="access-permissions"),
    *router.urls,
]
