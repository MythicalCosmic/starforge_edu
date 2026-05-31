from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "action", "resource_type", "resource_id", "actor")
    list_filter = ("action", "resource_type")
    search_fields = ("resource_type", "resource_id", "user_agent")
    readonly_fields = (
        "actor",
        "action",
        "resource_type",
        "resource_id",
        "changes",
        "ip",
        "user_agent",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
