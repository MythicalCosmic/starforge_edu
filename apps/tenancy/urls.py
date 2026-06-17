from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import CenterViewSet, ResolveView

router = DefaultRouter()
router.register(r"centers", CenterViewSet, basename="center")

urlpatterns = [
    # TD-19 tenant resolution — AllowAny, anon-throttled. Declared before the
    # router so the literal path is matched ahead of any router catch-all.
    path("resolve/", ResolveView.as_view(), name="platform-resolve"),
    *router.urls,
]
