"""Tenant Marketing Center scheduler: generate Content Studio drafts only; never publish."""
from __future__ import annotations

import logging

from django.db import transaction

from apps.core.context import get_context
from apps.core.db import fetch_all_dict, fetch_one
from apps.observability.tasks_base import TracedTask, run_in_platform_scope, run_in_tenant_scope
from config.celery import app

from . import services

logger = logging.getLogger("growth.marketing")


@app.task(base=TracedTask, name="marketing_center.dispatch_due_items", module="marketing_center")
def dispatch_due_items():
    """Every minute: lock due editorial items and enqueue one tenant-scoped draft-generation task."""
    def collect():
        with transaction.atomic():
            # Recover tasks whose worker disappeared. They are eligible for a bounded retry below.
            fetch_one("""UPDATE public.tenant_marketing_editorial_items
                            SET status='failed',generation_error='Generation worker timed out; retry scheduled',
                                updated_at=now()
                          WHERE status IN ('queued','generating') AND updated_at < now() - interval '30 minutes'
                            AND generation_attempts < 3 RETURNING id""")
            fetch_one("""UPDATE public.tenant_marketing_editorial_items
                            SET status='failed',generation_error='Generation retry limit reached after worker timeout',
                                updated_at=now()
                          WHERE status IN ('queued','generating') AND updated_at < now() - interval '30 minutes'
                            AND generation_attempts >= 3 RETURNING id""")
            due = fetch_all_dict("""SELECT i.id,i.tenant_id
                FROM public.tenant_marketing_editorial_items i
                JOIN public.tenant_marketing_campaigns c
                  ON c.id=i.campaign_id AND c.tenant_id=i.tenant_id
               WHERE c.status='active' AND c.generation_enabled=true
                 AND i.deleted_at IS NULL
                 AND i.status IN ('planned','failed')
                 AND i.generation_attempts < 3
                 AND i.planned_for <= (now() AT TIME ZONE c.timezone)::date
                 AND (now() AT TIME ZONE c.timezone)::time >= c.generation_time
               ORDER BY i.planned_for,i.created_at
               LIMIT 100 FOR UPDATE OF i SKIP LOCKED""")
            for item in due:
                fetch_one("""UPDATE public.tenant_marketing_editorial_items
                                SET status='queued',generation_attempts=generation_attempts+1,
                                    generation_error=NULL,updated_at=now()
                              WHERE id=%s AND tenant_id=%s RETURNING id""", [item["id"], item["tenant_id"]])
            return due

    due = run_in_platform_scope(collect)
    queued = 0
    for item in due:
        run_in_tenant_scope(str(item["tenant_id"]), lambda item=item: generate_editorial_item.delay_traced(str(item["id"])))
        queued += 1
    return {"due": len(due), "queued": queued}


@app.task(base=TracedTask, name="marketing_center.generate_editorial_item", module="marketing_center")
def generate_editorial_item(item_id: str):
    """Claim an item once, generate a Content Studio draft, and persist a retryable failure if needed."""
    claimed = fetch_one("""UPDATE public.tenant_marketing_editorial_items
                              SET status='generating',updated_at=now()
                            WHERE id=%s AND tenant_id=%s AND status='queued' AND deleted_at IS NULL
                            RETURNING id""", [item_id, get_context().tenant_id])
    if not claimed:
        return {"item_id": item_id, "status": "skipped", "reason": "not_queued_or_already_claimed"}
    try:
        result = services.generate_editorial_item(item_id)
        logger.info("Marketing article draft generated", extra={"item_id": item_id, "content_id": result.get("content_id")})
        return result
    except Exception as exc:  # noqa: BLE001 - persist a retryable item failure, do not publish or swallow task state
        fetch_one("""UPDATE public.tenant_marketing_editorial_items
                        SET status='failed',generation_error=%s,updated_at=now()
                      WHERE id=%s AND tenant_id=%s RETURNING id""",
                  [str(exc)[:2000], item_id, get_context().tenant_id])
        logger.exception("Marketing editorial draft generation failed", extra={"item_id": item_id})
        return {"item_id": item_id, "status": "failed", "error": str(exc)[:500]}
