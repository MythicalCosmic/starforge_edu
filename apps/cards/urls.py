from django.urls import path
from rest_framework.routers import DefaultRouter

from apps.cards.views import CardScanView, CardTypeViewSet, CardViewSet

router = DefaultRouter()
router.register("types", CardTypeViewSet, basename="card-type")
router.register("", CardViewSet, basename="card")

urlpatterns = [
    # Specific path before the catch-all "" card route.
    path("scan/", CardScanView.as_view(), name="card-scan"),
    *router.urls,
]
