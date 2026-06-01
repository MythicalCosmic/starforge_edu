from django.contrib import admin

from .models import Holiday, Lesson


@admin.register(Holiday)
class HolidayAdmin(admin.ModelAdmin):
    list_display = ("date", "name", "branch")
    list_filter = ("branch",)
    search_fields = ("name",)


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ("cohort", "start", "end", "room", "teacher", "status")
    list_filter = ("status", "branch")
    raw_id_fields = ("cohort", "branch", "room", "teacher")
    date_hierarchy = "start"
