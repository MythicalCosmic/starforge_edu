from django.urls import path
from rest_framework.routers import DefaultRouter

from apps.ai.views import (
    AIRequestViewSet,
    BudgetView,
    ExamGenerationView,
    UsageReportView,
)

router = DefaultRouter()
router.register("requests", AIRequestViewSet, basename="ai-requests")

urlpatterns = [
    path("budget/", BudgetView.as_view(), name="ai-budget"),
    path("exam-generation/", ExamGenerationView.as_view(), name="ai-exam-generation"),
    path("usage-report/", UsageReportView.as_view(), name="ai-usage-report"),
    *router.urls,
]
