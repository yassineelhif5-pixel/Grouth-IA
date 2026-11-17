"""Secret redaction for audit snapshots, logs and API payloads (pure Python)."""
from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

MASK = "••••••"
_SENSITIVE = re.compile(
    r"(pass(word|wd)?|secret|token|api[_-]?key|private[_-]?key|authorization|cookie|credential|"
    r"client[_-]?secret|refresh|access[_-]?key|signature|otp|mfa[_-]?code|cursor)", re.I)
_BEARER = re.compile(r"(?i)\b(bearer|basic)\s+[a-z0-9._~+/=-]+")
_JWT = re.compile(r"\beyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\b")


def is_sensitive_key(key: str, extra: Iterable[str] = ()) -> bool:
    return key in set(extra) or bool(_SENSITIVE.search(key))


def redact_text(text: str) -> str:
    return _JWT.sub(MASK, _BEARER.sub(lambda m: f"{m.group(1)} {MASK}", text))


def redact(value: Any, extra_keys: Iterable[str] = (), _depth: int = 0) -> Any:
    """Return a deep copy with sensitive keys masked. Never mutates the input."""
    extra = tuple(extra_keys)
    if _depth > 20:
        return MASK
    if isinstance(value, dict):
        return {k: (MASK if is_sensitive_key(str(k), extra) and v not in (None, "") else redact(v, extra, _depth + 1))
                for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [redact(v, extra, _depth + 1) for v in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def mask_hint(secret: str, visible: int = 4) -> str:
    """'sk-abcdef1234' → '••••1234' (for display only)."""
    if not secret:
        return ""
    return "••••" + secret[-visible:] if len(secret) > visible * 2 else MASK
