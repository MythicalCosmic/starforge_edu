from django.contrib import admin

from .models import EnrollmentEvent, StudentIdCounter, StudentProfile


@admin.register(StudentProfile)
class StudentProfileAdmin(admin.ModelAdmin):
    list_display = ("student_id", "status", "branch", "enrollment_date")
    list_filter = ("status", "branch")
    search_fields = ("student_id", "user__first_name", "user__last_name", "user__phone")
    raw_id_fields = ("user", "branch", "current_cohort")


@admin.register(EnrollmentEvent)
class EnrollmentEventAdmin(admin.ModelAdmin):
    list_display = ("student", "from_status", "to_status", "reason_code", "created_at")
    list_filter = ("to_status", "reason_code")
    raw_id_fields = ("student", "actor")


@admin.register(StudentIdCounter)
class StudentIdCounterAdmin(admin.ModelAdmin):
    list_display = ("year", "last_value")
