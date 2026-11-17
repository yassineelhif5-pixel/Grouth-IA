"""Supabase Storage (private buckets) through the backend service key: upload, signed URLs (short-lived)."""
from __future__ import annotations

import re

import requests
from django.conf import settings

from .exceptions import BusinessError


class StorageNotConfigured(BusinessError):
    status_code = 503
    code = "storage_not_configured"


def _base() -> tuple[str, dict]:
    if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_ROLE_KEY:
        raise StorageNotConfigured("Supabase Storage is not configured (SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY)")
    k = settings.SUPABASE_SERVICE_ROLE_KEY
    return f"{settings.SUPABASE_URL}/storage/v1", {"apikey": k, "Authorization": f"Bearer {k}"}


def safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name or "file")[:120] or "file"


def upload(bucket: str, path: str, data: bytes, content_type: str) -> str:
    base, h = _base()
    r = requests.post(f"{base}/object/{bucket}/{path}", data=data, headers={**h, "Content-Type": content_type, "x-upsert": "false"}, timeout=60)
    if r.status_code not in (200, 201):
        raise BusinessError(f"Storage upload failed ({r.status_code})", "storage_error", status_code=502)
    return f"{bucket}/{path}"


def signed_url(storage_path: str, expires: int | None = None) -> str:
    base, h = _base()
    bucket, path = storage_path.split("/", 1)
    r = requests.post(f"{base}/object/sign/{bucket}/{path}", json={"expiresIn": expires or settings.GROWTH["EXPORT_LINK_TTL_SECONDS"]},
                      headers=h, timeout=20)
    if r.status_code != 200:
        raise BusinessError("Could not sign the file URL", "storage_error", status_code=502)
    return f"{settings.SUPABASE_URL}/storage/v1{r.json()['signedURL']}"
