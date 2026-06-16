from rest_framework.routers import DefaultRouter

from .views import AssignmentViewSet, SubmissionViewSet

router = DefaultRouter()
# Register the nested `submissions` collection BEFORE the empty-prefix
# AssignmentViewSet so `/assignments/submissions/...` is not swallowed by the
# assignment `{pk}` detail route.
router.register("submissions", SubmissionViewSet, basename="submission")
router.register("", AssignmentViewSet, basename="assignment")

urlpatterns = router.urls
