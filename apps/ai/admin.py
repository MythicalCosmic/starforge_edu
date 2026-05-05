from django.contrib import admin

from .models import AiItem


@admin.register(AiItem)
class AiItemAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name",)
