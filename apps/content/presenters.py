"""Content response presenters (the DRF serializer output shapes)."""

from __future__ import annotations

from apps.content.models import (
    ContentLesson,
    ContentLibrary,
    Course,
    Folder,
    LessonFile,
    LibraryMaterial,
    Module,
)


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def library_to_dict(lib: ContentLibrary) -> dict:
    return {
        "id": lib.id,
        "name": lib.name,
        "description": lib.description,
        "visibility": lib.visibility,
        "department": lib.department_id,
        "cohort": lib.cohort_id,
        "allowed_roles": lib.allowed_roles,
        "is_active": lib.is_active,
    }


def course_to_dict(course: Course) -> dict:
    return {
        "id": course.id,
        "library": course.library_id,
        "subject": course.subject_id,
        "title": course.title,
        "description": course.description,
        "order": course.order,
    }


def module_to_dict(module: Module) -> dict:
    return {
        "id": module.id,
        "course": module.course_id,
        "title": module.title,
        "order": module.order,
    }


def lesson_to_dict(lesson: ContentLesson) -> dict:
    return {
        "id": lesson.id,
        "module": lesson.module_id,
        "title": lesson.title,
        "description": lesson.description,
        "order": lesson.order,
    }


def folder_to_dict(folder: Folder) -> dict:
    return {
        "id": folder.id,
        "library": folder.library_id,
        "parent": folder.parent_id,
        "name": folder.name,
    }


def lesson_file_to_dict(f: LessonFile) -> dict:
    thumbnail_url = None
    if f.thumbnail_key:
        from infrastructure.storage.s3_client import presign_download

        thumbnail_url = presign_download(f.thumbnail_key, expires_in=300)
    return {
        "id": f.id,
        "lesson": f.lesson_id,
        "folder": f.folder_id,
        "title": f.title,
        "content_type": f.content_type,
        "size_bytes": f.size_bytes,
        "status": f.status,
        "reject_reason": f.reject_reason,
        "version": f.version,
        "previous_version": f.previous_version_id,
        "thumbnail_url": thumbnail_url,
        "view_count": f.view_count,
        "download_count": f.download_count,
        "created_at": _iso(f.created_at),
        "is_approved_teacher": f.is_approved_teacher,
        "approved_teacher_by": f.approved_teacher_by_id,
        "approved_teacher_at": _iso(f.approved_teacher_at),
        "is_approved_manager": f.is_approved_manager,
        "approved_manager_by": f.approved_manager_by_id,
        "approved_manager_at": _iso(f.approved_manager_at),
        "is_downloadable": f.is_downloadable,
    }


def material_to_dict(m: LibraryMaterial) -> dict:
    return {
        "id": m.id,
        "library": m.library_id,
        "title": m.title,
        "topic": m.topic,
        "body": m.body,
        "status": m.status,
        "created_by": m.created_by_id,
        "published_at": _iso(m.published_at),
        "created_at": _iso(m.created_at),
        "updated_at": _iso(m.updated_at),
    }
