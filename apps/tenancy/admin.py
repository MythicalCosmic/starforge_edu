from django.contrib import admin
from django_tenants.admin import TenantAdminMixin

from .models import Center, Domain


@admin.register(Center)
class CenterAdmin(TenantAdminMixin, admin.ModelAdmin):
    list_display = ("name", "schema_name", "slug", "is_active", "on_trial", "created_at")
    list_filter = ("is_active", "on_trial")
    search_fields = ("name", "slug", "schema_name", "contact_email")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Domain)
class DomainAdmin(admin.ModelAdmin):
    list_display = ("domain", "tenant", "is_primary")
    search_fields = ("domain",)
    list_filter = ("is_primary",)
