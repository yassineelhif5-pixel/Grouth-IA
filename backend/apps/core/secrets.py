"""Backend-side encryption of secrets (Fernet / AES-128-CBC + HMAC). Keys never leave the backend,
ciphertexts are stored in `*_ciphertext` columns (excluded from history, audit and API payloads)."""
from __future__ import annotations

import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings

from .exceptions import BusinessError


class SecretsNotConfigured(BusinessError):
    status_code = 503
    code = "secrets_not_configured"


def _fernet() -> MultiFernet:
    keys = [k.strip() for k in (settings.SECRETS_ENCRYPTION_KEY or "").split(",") if k.strip()]
    if not keys:
        raise SecretsNotConfigured("SECRETS_ENCRYPTION_KEY is not configured on the backend")
    return MultiFernet([Fernet(k.encode()) for k in keys])  # first key encrypts, all keys decrypt (rotation)


def encrypt_json(data: dict[str, Any]) -> str:
    return _fernet().encrypt(json.dumps(data).encode()).decode()


def decrypt_json(token: str | None) -> dict[str, Any]:
    if not token:
        return {}
    try:
        return json.loads(_fernet().decrypt(token.encode()))
    except InvalidToken as e:
        raise SecretsNotConfigured("Secret cannot be decrypted with the configured keys") from e
