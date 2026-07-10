from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

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
    list_display = ("student_id", "first_name", "last_name", "phone", "status", "branch", "enrollment_date")
    list_filter = ("status", "branch", "gender")
    search_fields = ("student_id", "first_name", "last_name", "phone", "email", "user__username")
    autocomplete_fields = ("user", "branch", "current_cohort")
    list_select_related = ("user", "branch", "current_cohort")
    readonly_fields = ("login_account",)
    inlines = (EnrollmentEventInline,)

    @admin.display(description="Login username", ordering="user__username")
    def login_username(self, obj: StudentProfile) -> str:
        return obj.user.username

    @admin.display(description="Login account")
    def login_account(self, obj: StudentProfile):
        """Link to the User change page, where the login username + password are set
        (accounts are created passwordless; set a password so the student can sign in)."""
        if not obj.user_id:
            return "—"
        url = reverse("admin:users_user_change", args=[obj.user_id])
        return format_html('<a href="{}">{}</a> — set the login password here', url, obj.user.username)


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
