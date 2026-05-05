"""Identity models: User, Device, OTP, RoleMembership.

Login is by phone OR email — both are unique when set, both are nullable,
and a check constraint guarantees at least one of them is populated.

Roles are assigned via RoleMembership(user, branch, department, role).
The Branch and Department FK targets live in apps.org (TENANT_APPS only),
so RoleMembership only exists on tenant schemas.
"""

from __future__ import annotations

from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models
from django.db.models import CheckConstraint, Q
from django.utils import timezone

from .managers import UserManager


class User(AbstractBaseUser, PermissionsMixin):
    phone = models.CharField(max_length=32, unique=True, null=True, blank=True)
    email = models.EmailField(unique=True, null=True, blank=True)

    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    middle_name = models.CharField(max_length=150, blank=True)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    date_joined = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    objects = UserManager()

    USERNAME_FIELD = "phone"
    REQUIRED_FIELDS: list[str] = []  # createsuperuser will prompt for phone+password

    class Meta:
        constraints = [
            CheckConstraint(
                condition=Q(phone__isnull=False) | Q(email__isnull=False),
                name="user_phone_or_email_required",
            ),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return self.phone or self.email or f"user#{self.pk}"

    def get_full_name(self) -> str:
        parts = [self.first_name, self.middle_name, self.last_name]
        return " ".join(p for p in parts if p)

    def get_short_name(self) -> str:
        return self.first_name or self.phone or self.email or ""


class OTP(models.Model):
    """One-time password sent via SMS or email.

    The raw code is never stored — only its hash. `attempts` tracks
    verify attempts to prevent brute force; consume() marks it used.
    """

    PURPOSE_LOGIN = "login"
    PURPOSE_VERIFY = "verify"
    PURPOSE_RESET = "reset"
    PURPOSE_CHOICES = [
        (PURPOSE_LOGIN, "Login"),
        (PURPOSE_VERIFY, "Verify"),
        (PURPOSE_RESET, "Password reset"),
    ]

    CHANNEL_SMS = "sms"
    CHANNEL_EMAIL = "email"
    CHANNEL_CHOICES = [(CHANNEL_SMS, "SMS"), (CHANNEL_EMAIL, "Email")]

    identifier = models.CharField(max_length=255, db_index=True)  # phone or email
    channel = models.CharField(max_length=8, choices=CHANNEL_CHOICES)
    purpose = models.CharField(max_length=16, choices=PURPOSE_CHOICES, default=PURPOSE_LOGIN)
    code_hash = models.CharField(max_length=128)
    attempts = models.PositiveSmallIntegerField(default=0)
    consumed_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=("identifier", "consumed_at"))]


class Device(models.Model):
    PLATFORM_WEB = "web"
    PLATFORM_IOS = "ios"
    PLATFORM_ANDROID = "android"
    PLATFORM_CHOICES = [
        (PLATFORM_WEB, "Web"),
        (PLATFORM_IOS, "iOS"),
        (PLATFORM_ANDROID, "Android"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="devices")
    device_id = models.CharField(max_length=128)
    platform = models.CharField(max_length=16, choices=PLATFORM_CHOICES)
    push_token = models.TextField(blank=True)
    user_agent = models.CharField(max_length=512, blank=True)
    last_seen_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = (("user", "device_id"),)
        ordering = ("-last_seen_at",)


class RoleMembership(models.Model):
    """Assignment of a Role to a User scoped by Branch (and optionally Department).

    Branch and Department live in apps.org. Stored as integer FKs to avoid
    a circular dependency at model-import time.
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="role_memberships")
    branch = models.ForeignKey("org.Branch", on_delete=models.CASCADE, related_name="role_memberships")
    department = models.ForeignKey(
        "org.Department",
        on_delete=models.CASCADE,
        related_name="role_memberships",
        null=True,
        blank=True,
    )
    role = models.CharField(max_length=32)

    granted_at = models.DateTimeField(auto_now_add=True)
    granted_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="grants_made",
    )
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = (("user", "branch", "department", "role"),)
        ordering = ("-granted_at",)
