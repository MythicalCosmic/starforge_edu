from django.urls import path

from apps.intelligence.views import (
    BranchRankingView,
    FamilyHealthView,
    RiskDetailView,
    RiskListView,
    RulesView,
)

urlpatterns = [
    path("risk/", RiskListView.as_view(), name="risk-list"),
    path("risk/<int:student_id>/", RiskDetailView.as_view(), name="risk-detail"),
    path("branches/", BranchRankingView.as_view(), name="branch-ranking"),
    path("families/", FamilyHealthView.as_view(), name="family-health"),
    path("rules/", RulesView.as_view(), name="risk-rules"),
]
