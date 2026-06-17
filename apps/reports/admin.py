from django.contrib import admin

from apps.reports.models import Report, ReportRun, ReportSchedule


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ("key", "title", "default_format")
    list_filter = ("default_format",)
    search_fields = ("key", "title")


@admin.register(ReportRun)
class ReportRunAdmin(admin.ModelAdmin):
    list_display = ("id", "report", "format", "status", "file_bytes", "created_at", "finished_at")
    list_filter = ("status", "format", "report")
    search_fields = ("s3_key",)
    raw_id_fields = ("report", "requested_by")
    readonly_fields = ("created_at", "started_at", "finished_at")


@admin.register(ReportSchedule)
class ReportScheduleAdmin(admin.ModelAdmin):
    list_display = ("id", "report", "cadence", "weekday", "day_of_month", "hour", "is_active", "last_run_at")
    list_filter = ("cadence", "is_active", "report")
    raw_id_fields = ("report", "created_by")
    readonly_fields = ("last_run_at", "created_at", "updated_at")
