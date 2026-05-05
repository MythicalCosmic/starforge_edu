"""Custom UserManager that accepts phone OR email as the identifier."""

from __future__ import annotations

from typing import Any

from django.contrib.auth.base_user import BaseUserManager
from django.db import models

from core.validators import normalize_phone


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(
        self,
        *,
        phone: str | None,
        email: str | None,
        password: str | None,
        **extra_fields: Any,
    ) -> models.Model:
        if not phone and not email:
            raise ValueError("At least one of phone or email is required.")
        if email:
            email = self.normalize_email(email)
        if phone:
            phone = normalize_phone(phone)
        user = self.model(phone=phone, email=email, **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_user(
        self,
        phone: str | None = None,
        email: str | None = None,
        password: str | None = None,
        **extra_fields: Any,
    ) -> models.Model:
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(phone=phone, email=email, password=password, **extra_fields)

    def create_superuser(
        self,
        phone: str | None = None,
        email: str | None = None,
        password: str | None = None,
        **extra_fields: Any,
    ) -> models.Model:
        extra_fields["is_staff"] = True
        extra_fields["is_superuser"] = True
        extra_fields["is_active"] = True
        return self._create_user(phone=phone, email=email, password=password, **extra_fields)
