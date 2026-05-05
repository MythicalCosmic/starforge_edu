"""Seed a dev environment with a demo tenant + admin user.

After running, open http://demo.localhost:8000/admin/ (or hit the API
on demo.localhost:8000). Idempotent.
"""

from __future__ import annotations

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
django.setup()

from django_tenants.utils import schema_context  # noqa: E402

from apps.tenancy.models import Center  # noqa: E402
from apps.tenancy.services import provision_center  # noqa: E402
from apps.users.models import User  # noqa: E402


def main() -> None:
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
            phone="+998901234567",
            defaults={"is_staff": True, "is_superuser": True, "is_active": True},
        )
        if created or not admin.has_usable_password():
            admin.set_password("starforge-dev")
            admin.is_staff = True
            admin.is_superuser = True
            admin.save()
            print("created superuser phone=+998901234567 password=starforge-dev")
        else:
            print("superuser already exists")


if __name__ == "__main__":
    main()
