from django.contrib import admin

from .models import Lesson, RecurrenceRule, Term, TimeSlot


@admin.register(Term)
class TermAdmin(admin.ModelAdmin):
    list_display = ("academic_year", "name", "start_date", "end_date", "is_current")
    list_filter = ("academic_year", "is_current")


@admin.register(TimeSlot)
class TimeSlotAdmin(admin.ModelAdmin):
    list_display = ("branch", "name", "start_time", "end_time", "order")
    list_filter = ("branch",)


@admin.register(RecurrenceRule)
class RecurrenceRuleAdmin(admin.ModelAdmin):
    list_display = ("title", "cohort", "teacher", "term", "start_date", "end_date", "is_active")
    list_filter = ("is_active", "term")
    raw_id_fields = ("term", "cohort", "teacher", "room", "created_by")


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ("title", "cohort", "teacher", "room", "starts_at", "ends_at", "status")
    list_filter = ("status", "term")
    raw_id_fields = ("rule", "term", "cohort", "teacher", "room")
    date_hierarchy = "starts_at"
