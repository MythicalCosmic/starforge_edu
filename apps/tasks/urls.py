from rest_framework.routers import DefaultRouter

from apps.tasks.views import RoleGradeViewSet, TaskViewSet

router = DefaultRouter()
router.register("grades", RoleGradeViewSet, basename="role-grades")
router.register("", TaskViewSet, basename="tasks")

urlpatterns = router.urls
