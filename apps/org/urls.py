"""Org routes — plain function views (off DRF). Mounted at /api/v1/org/."""

from __future__ import annotations

from django.urls import path

from apps.org.views.v1.branch_views import (
    branch_delete_holiday_view,
    branch_detail_view,
    branch_holidays_view,
    branch_working_hours_view,
    branches_collection_view,
)
from apps.org.views.v1.department_views import department_detail_view, departments_collection_view
from apps.org.views.v1.room_views import room_detail_view, rooms_collection_view
from apps.org.views.v1.settings_views import settings_view
from apps.org.views.v1.transfer_views import transfer_detail_view, transfers_collection_view

urlpatterns = [
    path("settings/", settings_view, name="center-settings"),
    # branches (+ working-hours / holidays sub-resources)
    path("branches/", branches_collection_view, name="branches-collection"),
    path("branches/<int:pk>/", branch_detail_view, name="branches-detail"),
    path("branches/<int:pk>/working-hours/", branch_working_hours_view, name="branches-working-hours"),
    path("branches/<int:pk>/holidays/", branch_holidays_view, name="branches-holidays"),
    path(
        "branches/<int:pk>/holidays/<int:holiday_id>/",
        branch_delete_holiday_view,
        name="branches-delete-holiday",
    ),
    # departments
    path("departments/", departments_collection_view, name="departments-collection"),
    path("departments/<int:pk>/", department_detail_view, name="departments-detail"),
    # rooms
    path("rooms/", rooms_collection_view, name="rooms-collection"),
    path("rooms/<int:pk>/", room_detail_view, name="rooms-detail"),
    # transfers (read-only audit)
    path("transfers/", transfers_collection_view, name="transfers-collection"),
    path("transfers/<int:pk>/", transfer_detail_view, name="transfers-detail"),
]
