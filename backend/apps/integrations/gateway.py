"""Secure Integration Gateway — the only path from Growth IA to external APIs.

Every call: timeout, bounded retries with exponential backoff on 429/5xx, redacted logging,
persisted execution record (execution_logs) and usage event. React never calls providers directly."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import requests
from django.utils import timezone

from apps.audit.services import track_execution
from apps.core.context import get_context
from apps.core.db import fetch_one
from apps.core.exceptions import BusinessError
from apps.core.secrets import decrypt_json, encrypt_json

logger = logging.getLogger("growth.integrations")


class NotConfigured(BusinessError):
    status_code = 409
    code = "connector_not_configured"


class IntegrationError(BusinessError):
    status_code = 502
    code = "provider_error"


@dataclass
class Account:
    id: str
    tenant_id: str
    provider: str
    status: str
    settings: dict
    display_name: str


def load_account(account_id: str) -> Account:
    row = fetch_one("""SELECT a.id, a.tenant_id, p.code, a.status, a.settings, a.display_name
                         FROM public.tenant_connector_accounts a JOIN public.connector_providers p ON p.id = a.provider_id
                        WHERE a.id = %s AND a.deleted_at IS NULL""", [account_id])
    if not row:
        raise NotConfigured("Connector account not found")
    return Account(str(row[0]), str(row[1]), row[2], row[3], row[4] or {}, row[5])


def get_credentials(account_id: str) -> dict:
    row = fetch_one("""SELECT ciphertext FROM public.tenant_connector_credentials
                        WHERE account_id = %s AND deleted_at IS NULL ORDER BY created_at DESC LIMIT 1""", [account_id])
    if not row or not row[0]:
        raise NotConfigured("No credentials stored for this connector")
    return decrypt_json(row[0])


def store_credentials(account_id: str, tenant_id: str, credential_type: str, data: dict, hint: str = "",
                      expires_at=None) -> None:
    fetch_one("UPDATE public.tenant_connector_credentials SET deleted_at = now() WHERE account_id = %s AND deleted_at IS NULL RETURNING 1",
              [account_id])
    fetch_one("""INSERT INTO public.tenant_connector_credentials (tenant_id, account_id, credential_type, ciphertext, masked_hint, expires_at, rotated_at)
                 VALUES (%s, %s, %s, %s, %s, %s, now()) RETURNING id""",
              [tenant_id, account_id, credential_type, encrypt_json(data), hint, expires_at])


def set_status(account_id: str, status: str, error: str | None = None, tested: bool = False) -> None:
    fetch_one("""UPDATE public.tenant_connector_accounts SET status = %s, last_error = %s,
                        last_test_at = CASE WHEN %s THEN now() ELSE last_test_at END,
                        last_test_status = CASE WHEN %s THEN %s ELSE last_test_status END,
                        connected_at = CASE WHEN %s IN ('connected','tested') AND connected_at IS NULL THEN now() ELSE connected_at END
                  WHERE id = %s RETURNING 1""", [status, error, tested, tested, status, status, account_id])


def http(method: str, url: str, *, provider: str, operation: str, account_id: str | None = None,
         retries: int = 2, timeout: float = 20, expected: tuple[int, ...] = (200, 201, 202, 204), **kwargs: Any) -> requests.Response:
    ctx = get_context()
    with track_execution("integrations", f"{provider}:{operation}", input_summary={"method": method, "host": url.split("/")[2] if "//" in url else url}) as out:
        attempt = 0
        while True:
            attempt += 1
            try:
                resp = requests.request(method, url, timeout=timeout, **kwargs)
            except requests.RequestException as e:
                if attempt > retries:
                    raise IntegrationError(f"{provider} unreachable: {type(e).__name__}") from e
                time.sleep(min(2 ** attempt, 10))
                continue
            if resp.status_code in (429, 500, 502, 503, 504) and attempt <= retries:
                time.sleep(min(float(resp.headers.get("Retry-After", 2 ** attempt)), 30))
                continue
            break
        out["status_code"] = resp.status_code
        out["attempts"] = attempt
        if account_id and ctx.tenant_id:
            fetch_one("""INSERT INTO public.connector_usage_events (tenant_id, account_id, operation) VALUES (%s, %s, %s) RETURNING id""",
                      [ctx.tenant_id, account_id, operation])
        if resp.status_code not in expected:
            if account_id and ctx.tenant_id:
                fetch_one("""INSERT INTO public.connector_error_logs (tenant_id, account_id, error_code, error_message)
                             VALUES (%s, %s, %s, %s) RETURNING id""",
                          [ctx.tenant_id, account_id, str(resp.status_code), resp.text[:1000]])
            raise IntegrationError(f"{provider} {operation} failed: HTTP {resp.status_code}", details={"status": resp.status_code})
        return resp


def now_iso() -> str:
    return timezone.now().isoformat()
