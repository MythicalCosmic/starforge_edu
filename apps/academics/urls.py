from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    ExamViewSet,
    GradeRecomputeView,
    GradeViewSet,
    HonorRollView,
    SubjectViewSet,
    TranscriptViewSet,
    WarningsView,
)

router = DefaultRouter()
router.register("subjects", SubjectViewSet, basename="subject")
router.register("exams", ExamViewSet, basename="exam")
router.register("grades", GradeViewSet, basename="grade")
router.register("transcripts", TranscriptViewSet, basename="transcript")

urlpatterns = [
    # Explicit collection routes must precede the router's `{pk}` patterns.
    path("grades/recompute/", GradeRecomputeView.as_view(), name="grade-recompute"),
    path("honor-roll/", HonorRollView.as_view(), name="honor-roll"),
    path("warnings/", WarningsView.as_view(), name="warnings"),
    *router.urls,
]
