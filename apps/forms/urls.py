from rest_framework.routers import DefaultRouter

from apps.forms.views import FormViewSet

router = DefaultRouter()
router.register("", FormViewSet, basename="forms")

urlpatterns = router.urls
