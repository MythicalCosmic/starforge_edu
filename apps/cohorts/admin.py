from django.contrib import admin

from .models import Cohort, CohortMembership, CohortTeacher


@admin.register(Cohort)
class CohortAdmin(admin.ModelAdmin):
    list_display = ("name", "branch", "department", "primary_teacher", "is_archived")
    list_filter = ("is_archived", "branch", "department")
    search_fields = ("name", "level")
    raw_id_fields = ("branch", "department", "primary_teacher")


@admin.register(CohortMembership)
class CohortMembershipAdmin(admin.ModelAdmin):
    list_display = ("cohort", "student", "is_active", "start_date", "end_date")
    list_filter = ("is_active",)
    raw_id_fields = ("cohort", "student")


@admin.register(CohortTeacher)
class CohortTeacherAdmin(admin.ModelAdmin):
    list_display = ("cohort", "teacher", "created_at")
    raw_id_fields = ("cohort", "teacher")
