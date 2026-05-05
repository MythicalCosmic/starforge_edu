from django.contrib import admin

from .models import StudentItem


@admin.register(StudentItem)
class StudentItemAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name",)
