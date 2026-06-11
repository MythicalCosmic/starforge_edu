"""Seed a dev environment with a demo tenant + admin user.

After running, open http://demo.localhost:8000/admin/ (or hit the API
on demo.localhost:8000). Idempotent.
"""

from __future__ import annotations

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
django.setup()

from datetime import date  # noqa: E402

from django_tenants.utils import schema_context  # noqa: E402

from apps.tenancy.models import Center  # noqa: E402
from apps.tenancy.services import provision_center  # noqa: E402
from apps.users.models import User  # noqa: E402


def _seed_demo_domain(actor: User) -> None:
    """Seed a small, idempotent people domain for manual testing (D1-LD-10)."""
    from apps.cohorts.models import Cohort
    from apps.org.models import Branch, Department
    from apps.parents.services import create_parent, link_guardian
    from apps.students.models import StudentProfile
    from apps.students.services import create_student
    from apps.teachers.services import create_teacher
    from apps.users.models import RoleMembership
    from core.permissions import Role

    branch, _ = Branch.objects.get_or_create(slug="main", defaults={"name": "Main Branch"})
    department, _ = Department.objects.get_or_create(
        branch=branch, slug="general", defaults={"name": "General Studies"}
    )
    RoleMembership.objects.get_or_create(user=actor, branch=branch, department=None, role=Role.DIRECTOR)

    for i in (1, 2):
        phone = f"+99890111110{i}"
        if not User.objects.filter(phone=phone).exists():
            create_teacher(
                branch=branch,
                department=department,
                phone=phone,
                first_name=f"Teacher{i}",
                last_name="Demo",
            )

    cohort, _ = Cohort.objects.get_or_create(
        branch=branch,
        name="Group A",
        defaults={
            "department": department,
            "start_date": date(2026, 1, 1),
            "end_date": date(2026, 12, 31),
        },
    )

    from apps.cohorts.services import enroll_student_in_cohort

    for i in range(1, 6):
        phone = f"+99890222220{i}"
        if not User.objects.filter(phone=phone).exists():
            student = create_student(
                branch=branch,
                phone=phone,
                first_name=f"Student{i}",
                last_name="Demo",
                status=StudentProfile.Status.ACTIVE,
            )
            enroll_student_in_cohort(cohort=cohort, student=student)

    students = list(StudentProfile.objects.order_by("id")[:2])
    for i in (1, 2):
        phone = f"+99890333330{i}"
        if not User.objects.filter(phone=phone).exists():
            parent = create_parent(phone=phone, first_name=f"Parent{i}", last_name="Demo")
            if i - 1 < len(students):
                link_guardian(
                    parent=parent,
                    student=students[i - 1],
                    relationship="mother" if i == 1 else "father",
                    is_primary=True,
                )
    print("seeded demo domain: 1 branch, 1 department, 2 teachers, 1 cohort, 5 students, 2 parents")


def main() -> None:
    # Map the apex host to the public schema — without this Domain row,
    # django-tenants 404s http://localhost:8000/admin/ entirely.
    from django_tenants.utils import get_public_schema_name

    from apps.tenancy.models import Domain

    public_center, _ = Center.objects.get_or_create(
        schema_name=get_public_schema_name(),
        defaults={"name": "Platform", "slug": "platform"},
    )
    Domain.objects.get_or_create(domain="localhost", tenant=public_center, defaults={"is_primary": True})

    # Platform staff live in the public schema (TD-3 / ADR-007) so the apex
    # /admin/ and the platform API work. Login is username+password.
    platform_admin, p_created = User.objects.get_or_create(
        username="admin",
        defaults={
            "phone": "+998900000000",
            "is_staff": True,
            "is_superuser": True,
            "is_active": True,
        },
    )
    if p_created or not platform_admin.has_usable_password():
        platform_admin.set_password("starforge-platform")
        platform_admin.is_staff = True
        platform_admin.is_superuser = True
        platform_admin.save()
        print("created PLATFORM superuser admin / starforge-platform (apex /admin/)")
    else:
        print("platform superuser already exists")

    slug = "demo"
    hostname = "demo.localhost"
    if not Center.objects.filter(schema_name=slug).exists():
        provision_center(
            name="Demo Education Center",
            slug=slug,
            primary_domain=hostname,
            contact_name="Demo Admin",
            contact_phone="+998901234567",
            contact_email="admin@demo.localhost",
        )
        print(f"created Center {slug} @ {hostname}")
    else:
        print(f"Center {slug} already exists")

    with schema_context(slug):
        admin, created = User.objects.get_or_create(
            username="admin",
            defaults={
                "phone": "+998901234567",
                "is_staff": True,
                "is_superuser": True,
                "is_active": True,
            },
        )
        if created or not admin.has_usable_password():
            admin.set_password("starforge-dev")
            admin.is_staff = True
            admin.is_superuser = True
            admin.save()
            print("created tenant superuser admin / starforge-dev (demo.localhost)")
        else:
            print("superuser already exists")

        _seed_demo_domain(admin)


if __name__ == "__main__":
    main()
