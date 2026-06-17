"""Printing URLConf (D4-LD)."""

from __future__ import annotations

from django.urls import path
from rest_framework.routers import DefaultRouter

from apps.printing.views import (
    AgentClaimView,
    AgentJobStatusView,
    BranchAgentViewSet,
    PrinterViewSet,
    PrintJobViewSet,
)

router = DefaultRouter()
router.register("jobs", PrintJobViewSet, basename="printing-jobs")
router.register("printers", PrinterViewSet, basename="printing-printers")
router.register("agents", BranchAgentViewSet, basename="printing-agents")

urlpatterns = [
    path("agent/claim/", AgentClaimView.as_view(), name="printing-agent-claim"),
    path("agent/jobs/<int:job_id>/status/", AgentJobStatusView.as_view(), name="printing-agent-status"),
    *router.urls,
]
