from django.contrib import admin

from .models import Branch, Department


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "phone", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "slug", "address")


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("name", "branch", "slug", "is_active")
    list_filter = ("is_active", "branch")
    search_fields = ("name", "slug")
