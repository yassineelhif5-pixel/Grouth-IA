from apps.core.db import fetch_all_dict
from apps.observability.tasks_base import TracedTask, run_in_platform_scope, run_in_tenant_scope
from config.celery import app

from . import services as s


@app.task(base=TracedTask, name="email.classify", module="email_center", max_retries=2)
def classify_task(message_id: str):
    return s.classify(message_id)


@app.task(base=TracedTask, name="email.sync_mailbox", module="email_center", max_retries=0, autoretry_for=())
def sync_mailbox_task(mailbox_id: str):
    from .sync import sync_mailbox
    return sync_mailbox(mailbox_id)


@app.task(base=TracedTask, name="email.sync_all", module="email_center")
def sync_all():
    """Fallback synchronisation for every receiving mailbox, each in its own tenant scope."""
    boxes = run_in_platform_scope(lambda: fetch_all_dict(
        "SELECT id, tenant_id FROM public.email_mailboxes WHERE receive_mode IN ('gmail','graph','imap') AND status = 'active' AND deleted_at IS NULL"))
    done = 0
    for b in boxes:
        from .sync import sync_mailbox
        try:
            run_in_tenant_scope(str(b["tenant_id"]), lambda b=b: sync_mailbox(str(b["id"])))
            done += 1
        except Exception:  # noqa: BLE001 — failure persisted in email_sync_runs
            continue
    return {"mailboxes": len(boxes), "synced": done}
