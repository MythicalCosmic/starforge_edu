"""Field-level encryption at rest (TD-11).

`EncryptedTextField` / `EncryptedCharField` transparently Fernet-encrypt their
value on the way to the database and decrypt on the way back. Used for
`national_id`, `medical_notes`, provider credentials, and Soliq tokens.

The key comes from `settings.FIELD_ENCRYPTION_KEY` (separate from SECRET_KEY,
rotation runbook in docs/). Ciphertext is longer than plaintext, so both fields
store into a TEXT column; `max_length` still validates the *plaintext*.
"""

from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import models


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    key = getattr(settings, "FIELD_ENCRYPTION_KEY", "")
    if not key:
        raise ImproperlyConfigured("FIELD_ENCRYPTION_KEY is required for encrypted fields (TD-11).")
    return Fernet(key.encode() if isinstance(key, str) else key)


class _EncryptedMixin:
    def get_prep_value(self, value):
        value = super().get_prep_value(value)  # type: ignore[misc]
        if value is None or value == "":
            return value
        return _fernet().encrypt(str(value).encode()).decode()

    def from_db_value(self, value, expression, connection):
        if value is None or value == "":
            return value
        try:
            return _fernet().decrypt(value.encode()).decode()
        except InvalidToken:
            # Pre-existing plaintext or a key mismatch — surface the raw value
            # rather than crashing reads (rotation runbook handles migration).
            return value

    def to_python(self, value):
        return value


class EncryptedTextField(_EncryptedMixin, models.TextField):
    pass


class EncryptedCharField(_EncryptedMixin, models.CharField):
    def db_type(self, connection) -> str:
        # Ciphertext won't fit max_length; store as TEXT (max_length still
        # bounds the plaintext at the validation layer).
        return "text"
