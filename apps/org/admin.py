from django.contrib import admin

from .models import (
    Branch,
    BranchHoliday,
    BranchTransfer,
    BranchWorkingHours,
    CenterSettings,
    Department,
    Room,
)


class BranchWorkingHoursInline(admin.TabularInline):
    model = BranchWorkingHours
    extra = 0
    max_num = 7


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "phone", "is_active", "archived_at")
    list_filter = ("is_active",)
    search_fields = ("name", "slug", "address")
    inlines = (BranchWorkingHoursInline,)


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("name", "branch", "slug", "head", "budget", "is_active")
    list_filter = ("is_active", "branch")
    search_fields = ("name", "slug")


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ("name", "branch", "capacity", "is_active")
    list_filter = ("is_active", "branch")
    search_fields = ("name",)


@admin.register(BranchHoliday)
class BranchHolidayAdmin(admin.ModelAdmin):
    list_display = ("date", "name", "branch", "is_working_day_override")
    list_filter = ("branch", "is_working_day_override")
    search_fields = ("name",)
    date_hierarchy = "date"


@admin.register(BranchTransfer)
class BranchTransferAdmin(admin.ModelAdmin):
    """Read-only audit surface — transfers are written by services only."""

    list_display = ("user", "from_branch", "to_branch", "reason", "actor", "created_at")
    list_filter = ("from_branch", "to_branch")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CenterSettings)
class CenterSettingsAdmin(admin.ModelAdmin):
    """The per-tenant singleton (pk=1) — operator repair surface (TD-10)."""

    list_display = ("__str__", "grading_scheme", "currency_primary", "student_id_pattern", "updated_at")

    def has_add_permission(self, request):
        # Singleton: created lazily by CenterSettings.load(), never via admin.
        return not CenterSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
