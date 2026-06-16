from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    ContentLessonViewSet,
    ContentLibraryViewSet,
    ContentUploadUrlView,
    CourseViewSet,
    FolderViewSet,
    LessonFileViewSet,
    ModuleViewSet,
)

router = DefaultRouter()
router.register("libraries", ContentLibraryViewSet, basename="content-library")
router.register("courses", CourseViewSet, basename="content-course")
router.register("modules", ModuleViewSet, basename="content-module")
router.register("lessons", ContentLessonViewSet, basename="content-lesson")
router.register("folders", FolderViewSet, basename="content-folder")
router.register("files", LessonFileViewSet, basename="content-file")

urlpatterns = [
    path("upload-url/", ContentUploadUrlView.as_view(), name="content-upload-url"),
    *router.urls,
]
