from django.contrib import admin

from .models import ContentLesson, ContentLibrary, Course, FileView, Folder, LessonFile, Module


@admin.register(ContentLibrary)
class ContentLibraryAdmin(admin.ModelAdmin):
    list_display = ("name", "visibility", "department", "cohort", "is_active")
    list_filter = ("visibility", "is_active")
    search_fields = ("name",)


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("title", "library", "subject", "order")
    raw_id_fields = ("library", "subject")


@admin.register(Module)
class ModuleAdmin(admin.ModelAdmin):
    list_display = ("title", "course", "order")
    raw_id_fields = ("course",)


@admin.register(ContentLesson)
class ContentLessonAdmin(admin.ModelAdmin):
    list_display = ("title", "module", "order")
    raw_id_fields = ("module",)


@admin.register(Folder)
class FolderAdmin(admin.ModelAdmin):
    list_display = ("name", "library", "parent")
    raw_id_fields = ("library", "parent")


@admin.register(LessonFile)
class LessonFileAdmin(admin.ModelAdmin):
    list_display = ("title", "status", "content_type", "size_bytes", "version", "download_count")
    list_filter = ("status",)
    search_fields = ("title", "s3_key")
    raw_id_fields = ("lesson", "folder", "previous_version", "uploaded_by")


@admin.register(FileView)
class FileViewAdmin(admin.ModelAdmin):
    list_display = ("file", "user", "action", "created_at")
    list_filter = ("action",)
    raw_id_fields = ("file", "user")
