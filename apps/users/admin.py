from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import OTP, Device, RoleMembership, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ("-date_joined",)
    list_display = ("phone", "email", "first_name", "last_name", "is_staff", "is_active")
    search_fields = ("phone", "email", "first_name", "last_name")
    fieldsets = (
        (None, {"fields": ("phone", "email", "password")}),
        ("Identity", {"fields": ("first_name", "middle_name", "last_name")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Activity", {"fields": ("last_login", "last_seen_at", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("phone", "email", "password1", "password2"),
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
    search_fields = ("user__phone", "user__email", "device_id")


@admin.register(RoleMembership)
class RoleMembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "branch", "department", "granted_at", "revoked_at")
    list_filter = ("role",)
    search_fields = ("user__phone", "user__email")
