from django.contrib import admin

from .models import Cohort, CohortMembership, CohortTeacher


@admin.register(Cohort)
class CohortAdmin(admin.ModelAdmin):
    list_display = ("name", "branch", "department", "is_archived", "start_date", "end_date")
    list_filter = ("is_archived", "branch")
    search_fields = ("name", "level")
    raw_id_fields = ("branch", "department", "primary_teacher", "default_room")


@admin.register(CohortMembership)
class CohortMembershipAdmin(admin.ModelAdmin):
    list_display = ("cohort", "student", "start_date", "end_date")
    raw_id_fields = ("cohort", "student")


@admin.register(CohortTeacher)
class CohortTeacherAdmin(admin.ModelAdmin):
    list_display = ("cohort", "teacher", "role")
    raw_id_fields = ("cohort", "teacher")
