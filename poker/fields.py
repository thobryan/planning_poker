from __future__ import annotations

import base64
import hashlib
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import models

_ENCRYPTED_PREFIX = "enc$"


def _derive_key(secret: str) -> bytes:
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _get_fernet() -> Fernet:
    key = getattr(settings, "JIRA_TOKEN_ENCRYPTION_KEY", "") or ""
    if not key:
        key = _derive_key(settings.SECRET_KEY)
    if isinstance(key, str):
        key = key.encode("utf-8")
    try:
        return Fernet(key)
    except (TypeError, ValueError) as exc:
        raise ImproperlyConfigured("Invalid JIRA_TOKEN_ENCRYPTION_KEY.") from exc


def _decrypt(value: str) -> str:
    token = value[len(_ENCRYPTED_PREFIX) :]
    try:
        return _get_fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ImproperlyConfigured(
            "Unable to decrypt Jira token. Check JIRA_TOKEN_ENCRYPTION_KEY."
        ) from exc


class EncryptedTextField(models.TextField):
    def get_prep_value(self, value: Any) -> Any:
        value = super().get_prep_value(value)
        if value in (None, ""):
            return value
        if isinstance(value, str) and value.startswith(_ENCRYPTED_PREFIX):
            return value
        token = _get_fernet().encrypt(str(value).encode("utf-8")).decode("utf-8")
        return f"{_ENCRYPTED_PREFIX}{token}"

    def from_db_value(self, value, expression, connection):
        if value in (None, ""):
            return value
        if isinstance(value, str) and value.startswith(_ENCRYPTED_PREFIX):
            return _decrypt(value)
        return value

    def to_python(self, value):
        if value in (None, ""):
            return value
        if isinstance(value, str) and value.startswith(_ENCRYPTED_PREFIX):
            return _decrypt(value)
        return value
