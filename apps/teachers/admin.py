from django.contrib import admin

from .models import TeacherProfile


@admin.register(TeacherProfile)
class TeacherProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "department", "employment_type", "payout_percent", "is_active")
    list_filter = ("employment_type", "is_active", "department")
    search_fields = ("user__phone", "user__email", "user__first_name", "user__last_name")
    raw_id_fields = ("user",)
