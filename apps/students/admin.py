from django.contrib import admin

from core.admin_mixins import ReadOnlyAdmin

from .models import EnrollmentEvent, EnrollmentReason, StudentIdCounter, StudentProfile


@admin.register(EnrollmentReason)
class EnrollmentReasonAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "color", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}


class EnrollmentEventInline(admin.TabularInline):
    """The student's status-change history, read-only (written by the transition
    service, not by hand)."""

    model = EnrollmentEvent
    extra = 0
    fields = ("from_status", "to_status", "reason_code", "note", "actor", "created_at")
    readonly_fields = fields
    can_delete = False
    show_change_link = True

    def has_add_permission(self, request, obj=None) -> bool:
        return False


@admin.register(StudentProfile)
class StudentProfileAdmin(admin.ModelAdmin):
    list_display = ("student_id", "status", "branch", "current_cohort", "enrollment_date")
    list_filter = ("status", "branch")
    search_fields = ("student_id", "user__first_name", "user__last_name", "user__phone", "user__username")
    autocomplete_fields = ("user", "branch", "current_cohort")
    inlines = (EnrollmentEventInline,)


@admin.register(EnrollmentEvent)
class EnrollmentEventAdmin(ReadOnlyAdmin):
    """The enrollment status-change log — written by the transition service, so
    view-only here (matches the audit/ledger pattern)."""

    list_display = ("student", "from_status", "to_status", "reason_code", "actor", "created_at")
    list_filter = ("to_status", "reason_code")
    search_fields = ("student__student_id", "reason_code")
    autocomplete_fields = ("student", "actor")
    date_hierarchy = "created_at"


@admin.register(StudentIdCounter)
class StudentIdCounterAdmin(ReadOnlyAdmin):
    """Internal per-year sequence that mints student IDs — never hand-edited."""

    list_display = ("year", "last_value")
