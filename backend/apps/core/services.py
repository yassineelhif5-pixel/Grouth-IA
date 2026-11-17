"""Transactional, audited write helpers used by every Django service.

Each helper: (1) validates optimistic version, (2) writes the change, (3) lets the DB trigger
version it into entity_history, (4) writes the audit event + activity — all in ONE transaction.
"""
from __future__ import annotations

import contextlib
from typing import Any

from django.db import transaction
from django.utils import timezone
from rest_framework import status

from apps.audit.services import record_activity, record_audit

from .context import get_context, set_context
from .db import apply_db_context
from .exceptions import BusinessError
from .serialization import snapshot


@contextlib.contextmanager
def change_reason(reason: str | None):
    """Attach a human reason to the next writes (stored in entity_history.change_reason)."""
    ctx = get_context()
    if not reason:
        yield
        return
    set_context(ctx.with_(change_reason=reason[:500]))
    apply_db_context(get_context())
    try:
        yield
    finally:
        set_context(ctx)
        apply_db_context(ctx)


def _entity(instance) -> str:
    return instance._meta.db_table


def audited_create(model, data: dict, *, action: str, module: str, description: str = "",
                   product_id: str | None = None, reason: str | None = None):
    ctx = get_context()
    if "tenant_id" in [f.attname for f in model._meta.concrete_fields] and ctx.tenant_id:
        data = {**data, "tenant_id": ctx.tenant_id}  # tenant always from the verified context
    with transaction.atomic(), change_reason(reason):
        obj = model.objects.create(**data)
        obj.refresh_from_db()
        record_audit(action, module, entity_type=_entity(obj), entity_id=obj.pk, after=snapshot(obj),
                     description=description or f"{_entity(obj)} created", secret_fields=getattr(obj, "SECRET_FIELDS", ()))
        record_activity(action, module, entity_type=_entity(obj), entity_id=obj.pk, product_id=product_id,
                        description=description)
    return obj


def audited_update(instance, changes: dict[str, Any], *, action: str, module: str, description: str = "",
                   expected_version: int | None = None, reason: str | None = None, product_id: str | None = None):
    if expected_version is not None and hasattr(instance, "version_number") and int(expected_version) != instance.version_number:
        raise BusinessError("This record was modified by someone else. Reload and retry.", "version_conflict",
                            {"current_version": instance.version_number}, status.HTTP_409_CONFLICT)
    changes = {k: v for k, v in changes.items() if k not in ("id", "tenant_id", "tenant", "version_number")}
    before = snapshot(instance)
    with transaction.atomic(), change_reason(reason):
        for k, v in changes.items():
            setattr(instance, k, v)
        instance.save(update_fields=list(changes.keys()) or None)
        instance.refresh_from_db()
        after = snapshot(instance)
        diff_before = {k: before.get(k) for k in after if before.get(k) != after.get(k)}
        diff_after = {k: after.get(k) for k in diff_before}
        if diff_after:
            record_audit(action, module, entity_type=_entity(instance), entity_id=instance.pk, before=diff_before,
                         after=diff_after, description=description or f"{_entity(instance)} updated",
                         secret_fields=getattr(instance, "SECRET_FIELDS", ()))
            record_activity(action, module, entity_type=_entity(instance), entity_id=instance.pk,
                            product_id=product_id, description=description, metadata={"fields": sorted(diff_after)})
    return instance


def audited_soft_delete(instance, *, action: str, module: str, reason: str):
    if not reason:
        raise BusinessError("A reason is required for deletion", "reason_required")
    return audited_update(instance, {"deleted_at": timezone.now()}, action=action, module=module,
                          description=f"{_entity(instance)} deleted: {reason}", reason=reason)


def audited_restore(instance, *, action: str, module: str, reason: str):
    return audited_update(instance, {"deleted_at": None}, action=action, module=module,
                          description=f"{_entity(instance)} restored: {reason}", reason=reason)
