from django.contrib import admin

from .models import TeacherProfile


@admin.register(TeacherProfile)
class TeacherProfileAdmin(admin.ModelAdmin):
    list_display = ("first_name", "last_name", "phone", "branch", "department", "salary_type", "is_substitute")
    list_filter = ("salary_type", "is_substitute", "branch", "gender")
    search_fields = ("first_name", "last_name", "phone", "email", "user__username")
    autocomplete_fields = ("user", "branch", "department")
    list_select_related = ("user", "branch", "department")
