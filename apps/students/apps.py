from django.apps import AppConfig


class StudentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.students"
    label = "students"
    verbose_name = "Students"

    def ready(self) -> None:
        from apps.students.interfaces.repositories import IStudentRepository
        from apps.students.interfaces.student_service import IStudentService
        from apps.students.repositories.student_repository import StudentRepository
        from apps.students.services.v1.student_service import StudentService
        from core.container import container

        container.register(IStudentRepository, StudentRepository)
        container.register(IStudentService, StudentService)
