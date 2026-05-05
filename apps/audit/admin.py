from django.contrib import admin

from .models import AuditItem


@admin.register(AuditItem)
class AuditItemAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name",)
