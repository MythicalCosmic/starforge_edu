from django.contrib import admin

from .models import ParentItem


@admin.register(ParentItem)
class ParentItemAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name",)
