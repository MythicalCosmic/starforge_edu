from django.contrib import admin

from .models import Exam, ExamResult, Grade, Subject, Transcript


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "department", "is_active")
    list_filter = ("is_active", "department")
    search_fields = ("name", "code")


@admin.register(Exam)
class ExamAdmin(admin.ModelAdmin):
    list_display = ("title", "subject", "cohort", "term", "type", "is_published", "exam_date")
    list_filter = ("type", "is_published", "term")
    search_fields = ("title",)
    raw_id_fields = ("subject", "cohort", "term", "created_by")
    date_hierarchy = "exam_date"


@admin.register(ExamResult)
class ExamResultAdmin(admin.ModelAdmin):
    list_display = ("exam", "student", "score", "graded_by", "graded_at")
    search_fields = ("student__student_id",)
    raw_id_fields = ("exam", "student", "graded_by")


@admin.register(Grade)
class GradeAdmin(admin.ModelAdmin):
    list_display = ("student", "subject", "term", "value_raw", "value_display", "is_published")
    list_filter = ("is_published", "term", "subject")
    search_fields = ("student__student_id",)
    raw_id_fields = ("student", "subject", "term")


@admin.register(Transcript)
class TranscriptAdmin(admin.ModelAdmin):
    list_display = ("id", "student", "term", "status", "generated_at", "created_at")
    list_filter = ("status",)
    search_fields = ("student__student_id",)
    raw_id_fields = ("student", "term", "requested_by")
