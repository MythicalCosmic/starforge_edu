from django.contrib import admin

from .models import NotificationItem


@admin.register(NotificationItem)
class NotificationItemAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name",)
