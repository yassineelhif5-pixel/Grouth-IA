from __future__ import annotations

import logging

from apps.audit.services import track_execution
from apps.core.db import fetch_all_dict, fetch_one

from .checks import REGISTRY, CheckResult

logger = logging.getLogger("growth.health")


def run_checks(codes: list[str] | None = None) -> list[dict]:
    """Run checks and persist every result (system_health_results). Requires platform scope context."""
    out = []
    checks = fetch_all_dict("SELECT id, code FROM public.system_health_checks WHERE is_enabled ORDER BY code")
    for chk in checks:
        if codes and chk["code"] not in codes:
            continue
        fn = REGISTRY.get(chk["code"])
        with track_execution("system_health", f"check:{chk['code']}") as exec_out:
            try:
                res = fn() if fn else CheckResult("unknown", error="no probe implemented")
            except Exception as e:  # noqa: BLE001
                logger.exception("health check %s crashed", chk["code"])
                res = CheckResult("down", error=f"{type(e).__name__}: {str(e)[:300]}")
            exec_out["status"] = res.status
        fetch_one("""INSERT INTO public.system_health_results (check_id, status, latency_ms, error_message, recommendation, details)
                     VALUES (%s, %s, %s, %s, %s, %s::jsonb) RETURNING id""",
                  [chk["id"], res.status, res.latency_ms, res.error, res.recommendation, __import__("json").dumps(res.details)])
        out.append({"code": chk["code"], "status": res.status, "latency_ms": res.latency_ms, "error": res.error,
                    "recommendation": res.recommendation, "details": res.details})
    return out


def latest_status() -> list[dict]:
    return fetch_all_dict("""SELECT s.code AS service, s.name AS service_name, s.category, c.code, c.name,
                                    r.status, r.latency_ms, r.error_message, r.recommendation, r.details, r.created_at AS checked_at
                               FROM public.system_health_checks c JOIN public.system_services s ON s.id = c.service_id
                               LEFT JOIN LATERAL (SELECT * FROM public.system_health_results x WHERE x.check_id = c.id
                                                   ORDER BY x.created_at DESC LIMIT 1) r ON true
                              ORDER BY s.code, c.code""")
