from rest_framework.routers import DefaultRouter

from .views import CohortMembershipViewSet, CohortTeacherViewSet, CohortViewSet

router = DefaultRouter()
router.register(r"memberships", CohortMembershipViewSet, basename="cohort-memberships")
router.register(r"co-teachers", CohortTeacherViewSet, basename="cohort-teachers")
router.register(r"", CohortViewSet, basename="cohorts")

urlpatterns = router.urls
