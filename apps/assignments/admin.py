from django.contrib import admin

from .models import Assignment, Submission, SubmissionGrade


@admin.register(Assignment)
class AssignmentAdmin(admin.ModelAdmin):
    list_display = ("title", "cohort", "status", "due_at", "published_at")
    list_filter = ("status",)
    search_fields = ("title",)
    raw_id_fields = ("cohort", "created_by")
    date_hierarchy = "due_at"


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = ("assignment", "student", "attempt_number", "is_late", "status", "submitted_at")
    list_filter = ("status", "is_late")
    search_fields = ("student__student_id",)
    raw_id_fields = ("assignment", "student")


@admin.register(SubmissionGrade)
class SubmissionGradeAdmin(admin.ModelAdmin):
    list_display = ("submission", "score", "graded_by", "graded_at")
    raw_id_fields = ("submission", "graded_by")
