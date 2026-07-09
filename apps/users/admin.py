from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from core.admin_mixins import ReadOnlyAdmin

from .models import OTP, Device, RoleMembership, Session, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ("-date_joined",)
    list_display = ("username", "phone", "email", "first_name", "last_name", "is_staff", "is_active")
    search_fields = ("username", "phone", "email", "first_name", "last_name")
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Contacts", {"fields": ("phone", "email")}),
        ("Identity", {"fields": ("first_name", "middle_name", "last_name")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Activity", {"fields": ("last_login", "last_seen_at", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("username", "phone", "email", "password1", "password2"),
            },
        ),
    )
    readonly_fields = ("last_login", "last_seen_at", "date_joined")


@admin.register(OTP)
class OTPAdmin(admin.ModelAdmin):
    list_display = ("identifier", "channel", "purpose", "consumed_at", "expires_at", "attempts", "created_at")
    list_filter = ("channel", "purpose")
    search_fields = ("identifier",)


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ("user", "platform", "device_id", "last_seen_at", "revoked_at")
    list_filter = ("platform",)
    search_fields = ("user__username", "user__phone", "user__email", "device_id")


@admin.register(RoleMembership)
class RoleMembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "branch", "department", "granted_at", "revoked_at")
    list_filter = ("role",)
    search_fields = ("user__username", "user__phone", "user__email")


@admin.register(Session)
class SessionAdmin(ReadOnlyAdmin):
    """View-only. ``key`` is a live Bearer token — never list, search, or render
    it (exposing it lets a viewer impersonate the user), so it is excluded from
    the form entirely. Session lifecycle is owned by the auth service."""

    list_display = ("id", "user", "ip_address", "device_id", "read_only", "created_at",
                    "last_used_at", "expires_at", "revoked_at")
    list_filter = ("read_only",)
    search_fields = ("user__username", "ip_address", "device_id")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    exclude = ("key",)
