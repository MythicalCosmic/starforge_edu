from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    IcalFeedView,
    IcalUrlView,
    LessonViewSet,
    RecurrenceRuleViewSet,
    TermViewSet,
    TimeSlotViewSet,
)

router = DefaultRouter()
router.register("terms", TermViewSet, basename="term")
router.register("timeslots", TimeSlotViewSet, basename="timeslot")
router.register("rules", RecurrenceRuleViewSet, basename="rule")
router.register("lessons", LessonViewSet, basename="lesson")

urlpatterns = [
    path("ical-url/", IcalUrlView.as_view(), name="ical-url"),
    path("ical/<str:token>/", IcalFeedView.as_view(), name="ical-feed"),
    *router.urls,
]
