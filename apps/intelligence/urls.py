from django.urls import path

from apps.intelligence.views import RiskDetailView, RiskListView, RulesView

urlpatterns = [
    path("risk/", RiskListView.as_view(), name="risk-list"),
    path("risk/<int:student_id>/", RiskDetailView.as_view(), name="risk-detail"),
    path("rules/", RulesView.as_view(), name="risk-rules"),
]
