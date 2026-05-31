from django.contrib import admin

from .models import StudentProfile


@admin.register(StudentProfile)
class StudentProfileAdmin(admin.ModelAdmin):
    list_display = ("student_id", "user", "branch", "status", "enrollment_date")
    list_filter = ("status", "branch")
    search_fields = ("student_id", "user__phone", "user__email", "user__first_name", "user__last_name")
    raw_id_fields = ("user", "branch")
