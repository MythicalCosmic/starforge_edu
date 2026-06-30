from django.urls import path

from apps.teachers.views.v1.teacher_views import (
    teacher_dashboard_view,
    teacher_detail_view,
    teachers_collection_view,
)

urlpatterns = [
    path("dashboard/", teacher_dashboard_view, name="teacher-dashboard"),
    path("", teachers_collection_view, name="teachers-list"),
    path("<int:pk>/", teacher_detail_view, name="teachers-detail"),
]
