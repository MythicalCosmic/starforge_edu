from django.contrib import admin

from .models import Guardian, ParentProfile


@admin.register(ParentProfile)
class ParentProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "occupation", "workplace", "created_at")
    search_fields = ("user__phone", "user__email", "user__first_name", "user__last_name")
    raw_id_fields = ("user",)


@admin.register(Guardian)
class GuardianAdmin(admin.ModelAdmin):
    list_display = ("parent", "student", "relationship", "is_primary", "can_pickup")
    list_filter = ("relationship", "is_primary", "can_pickup")
    raw_id_fields = ("parent", "student")
