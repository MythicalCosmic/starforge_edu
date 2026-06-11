from django.contrib import admin

from .models import Guardian, ParentProfile, PickupAuthorization


@admin.register(ParentProfile)
class ParentProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "workplace", "created_at")
    search_fields = ("user__first_name", "user__last_name", "user__phone")
    raw_id_fields = ("user",)


@admin.register(Guardian)
class GuardianAdmin(admin.ModelAdmin):
    list_display = ("parent", "student", "relationship", "is_primary")
    list_filter = ("relationship", "is_primary")
    raw_id_fields = ("parent", "student")


@admin.register(PickupAuthorization)
class PickupAuthorizationAdmin(admin.ModelAdmin):
    list_display = ("student", "full_name", "phone", "is_active")
    list_filter = ("is_active",)
    raw_id_fields = ("student",)
