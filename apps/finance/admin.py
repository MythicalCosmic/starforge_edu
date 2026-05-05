from django.contrib import admin

from .models import FinanceItem


@admin.register(FinanceItem)
class FinanceItemAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name",)
