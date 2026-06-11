from django.contrib import admin

from .models import TeacherProfile


@admin.register(TeacherProfile)
class TeacherProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "branch", "department", "salary_type", "is_substitute")
    list_filter = ("salary_type", "is_substitute", "branch")
    search_fields = ("user__first_name", "user__last_name", "user__phone")
    raw_id_fields = ("user", "branch", "department")
