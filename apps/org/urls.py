from rest_framework.routers import DefaultRouter

from .views import BranchViewSet, DepartmentViewSet

router = DefaultRouter()
router.register(r"branches", BranchViewSet, basename="branch")
router.register(r"departments", DepartmentViewSet, basename="department")

urlpatterns = router.urls
