from django.contrib import admin

from .models import AttendanceRecord


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = ("student", "lesson", "status", "auto_marked", "marked_by", "marked_at")
    list_filter = ("status", "auto_marked")
    search_fields = ("student__student_id", "lesson__title")
    raw_id_fields = ("student", "lesson", "marked_by")
    date_hierarchy = "created_at"
