from django.contrib import admin

from apps.notifications.models import (
    Notification,
    NotificationDelivery,
    NotificationPreference,
    NotificationTemplate,
)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "event_type", "title", "read_at", "created_at")
    list_filter = ("event_type", "read_at")
    search_fields = ("title", "dedupe_key")
    raw_id_fields = ("user",)
    date_hierarchy = "created_at"


@admin.register(NotificationDelivery)
class NotificationDeliveryAdmin(admin.ModelAdmin):
    list_display = ("id", "notification", "channel", "status", "sent_at", "created_at")
    list_filter = ("channel", "status")
    raw_id_fields = ("notification",)


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "event_type", "channel", "enabled")
    list_filter = ("event_type", "channel", "enabled")
    raw_id_fields = ("user",)


@admin.register(NotificationTemplate)
class NotificationTemplateAdmin(admin.ModelAdmin):
    list_display = ("id", "event_type", "channel", "locale", "is_active")
    list_filter = ("event_type", "channel", "locale", "is_active")
    search_fields = ("subject", "body")
