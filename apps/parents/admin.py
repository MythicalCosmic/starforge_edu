from django.contrib import admin

from .models import Guardian, ParentProfile, PickupAuthorization


class GuardianInline(admin.TabularInline):
    """The parent's guardianship links to students (editable)."""

    model = Guardian
    extra = 0
    fields = ("student", "relationship", "is_primary", "custody_notes")
    autocomplete_fields = ("student",)
    show_change_link = True


@admin.register(ParentProfile)
class ParentProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "first_name", "last_name", "phone", "workplace", "created_at")
    list_filter = ("gender",)
    search_fields = ("first_name", "last_name", "phone", "email", "user__username")
    autocomplete_fields = ("user",)
    list_select_related = ("user",)
    inlines = (GuardianInline,)


@admin.register(Guardian)
class GuardianAdmin(admin.ModelAdmin):
    list_display = ("parent", "student", "relationship", "is_primary")
    list_filter = ("relationship", "is_primary")
    autocomplete_fields = ("parent", "student")
    list_select_related = ("parent", "student")


@admin.register(PickupAuthorization)
class PickupAuthorizationAdmin(admin.ModelAdmin):
    list_display = ("student", "full_name", "phone", "is_active")
    list_filter = ("is_active",)
    search_fields = ("full_name", "phone")
    autocomplete_fields = ("student",)
    list_select_related = ("student",)
