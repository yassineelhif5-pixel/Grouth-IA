"""Centre d'historique: filtered queries over the 4 traceability levels, version compare & restore."""
from __future__ import annotations

from datetime import datetime

from django.apps import apps as django_apps

from apps.core.context import parse_uuid
from apps.core.db import fetch_all_dict
from apps.core.exceptions import BusinessError
from apps.core.services import audited_update

META_FIELDS = {"id", "tenant_id", "created_at", "updated_at", "created_by", "updated_by", "version_number", "correlation_id",
               "deleted_at"}
MAX_PAGE = 500


def model_for_table(table: str):
    for m in django_apps.get_models():
        if m._meta.db_table == table and getattr(m, "TRACE_KIND", None) in ("biz", "conf", "gbiz"):
            return m
    raise BusinessError("Unknown or non-versioned entity type", "unknown_entity", status_code=404)


def _parse_dt(v: str | None):
    if not v:
        return None
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError as e:
        raise BusinessError(f"Invalid date: {v}", "invalid_filter") from e


def build_filters(params, *, tenant_id: str | None, columns: dict[str, str], time_col: str = "created_at"):
    """Translate query params into a parameterised WHERE clause. Unknown params are ignored."""
    where, args = [], []
    if tenant_id is not None:
        where.append("tenant_id = %s")
        args.append(tenant_id)
    elif params.get("tenant_id"):
        where.append("tenant_id = %s")
        args.append(parse_uuid(params["tenant_id"]))
    if (d := _parse_dt(params.get("from"))):
        where.append(f"{time_col} >= %s")
        args.append(d)
    if (d := _parse_dt(params.get("to"))):
        where.append(f"{time_col} < %s")
        args.append(d)
    for param, col in columns.items():
        value = params.get(param)
        if not value:
            continue
        if col.endswith("_id") or col in ("entity_id", "correlation_id", "request_id", "execution_id"):
            value = parse_uuid(value)
            if not value:
                raise BusinessError(f"Invalid {param}", "invalid_filter")
        where.append(f"{col} = %s")
        args.append(value)
    return (" WHERE " + " AND ".join(where)) if where else "", args


def page_args(params) -> tuple[int, int]:
    size = min(max(int(params.get("page_size", 50) or 50), 1), MAX_PAGE)
    page = max(int(params.get("page", 1) or 1), 1)
    return size, (page - 1) * size


AUDIT_FILTERS = {"user": "actor_user_id", "module": "module", "action": "action", "entity_type": "entity_type",
                 "entity_id": "entity_id", "status": "status", "correlation_id": "correlation_id", "request_id": "request_id",
                 "actor_type": "actor_type"}
ACTIVITY_FILTERS = {"user": "user_id", "module": "module", "event_type": "event_type", "entity_type": "entity_type",
                    "entity_id": "entity_id", "product": "product_id", "correlation_id": "correlation_id"}
EXEC_FILTERS = {"module": "module", "operation": "operation", "status": "status", "execution": "execution_id",
                "correlation_id": "correlation_id", "request_id": "request_id"}


def query_audit(params, tenant_id: str | None, show_values: bool) -> dict:
    where, args = build_filters(params, tenant_id=tenant_id, columns=AUDIT_FILTERS)
    size, offset = page_args(params)
    values = "before_data, after_data," if show_values else "NULL::jsonb AS before_data, NULL::jsonb AS after_data,"
    rows = fetch_all_dict(f"""SELECT id, tenant_id, created_at, actor_user_id, actor_type, action, module, entity_type, entity_id,
                                     description, {values} source, status, request_id, correlation_id
                                FROM public.audit_events{where} ORDER BY created_at DESC, id DESC LIMIT %s OFFSET %s""",
                          args + [size + 1, offset])
    return {"results": rows[:size], "has_more": len(rows) > size, "page_size": size}


def query_simple(table: str, cols: str, filters: dict, params, tenant_id: str | None) -> dict:
    where, args = build_filters(params, tenant_id=tenant_id, columns=filters)
    size, offset = page_args(params)
    rows = fetch_all_dict(f"SELECT {cols} FROM public.{table}{where} ORDER BY created_at DESC LIMIT %s OFFSET %s",  # noqa: S608
                          args + [size + 1, offset])
    return {"results": rows[:size], "has_more": len(rows) > size, "page_size": size}


def entity_versions(entity_type: str, entity_id: str, tenant_id: str | None, show_values: bool) -> list[dict]:
    model_for_table(entity_type)  # whitelist
    values = "previous_data, current_data," if show_values else ""
    where = "entity_type = %s AND entity_id = %s" + (" AND tenant_id = %s" if tenant_id else "")
    args = [entity_type, entity_id] + ([tenant_id] if tenant_id else [])
    return fetch_all_dict(f"""SELECT id, version_number, operation, changed_fields, {values} changed_by, actor_type,
                                     change_reason, correlation_id, created_at
                                FROM public.entity_history WHERE {where} ORDER BY version_number DESC""", args)


def compare_versions(entity_type: str, entity_id: str, v_from: int, v_to: int, tenant_id: str | None) -> dict:
    rows = {r["version_number"]: r for r in entity_versions(entity_type, entity_id, tenant_id, True)}
    a, b = rows.get(v_from), rows.get(v_to)
    if not a or not b:
        raise BusinessError("Version not found", "version_not_found", status_code=404)
    da, db = a["current_data"] or a["previous_data"] or {}, b["current_data"] or b["previous_data"] or {}
    keys = sorted(set(da) | set(db))
    return {"from": v_from, "to": v_to,
            "changes": [{"field": k, "from": da.get(k), "to": db.get(k)} for k in keys if da.get(k) != db.get(k) and k not in
                        ("updated_at", "updated_by", "version_number")]}


def restore_version(entity_type: str, entity_id: str, version: int, reason: str, tenant_id: str | None):
    """Controlled restore: the old values are written as a NEW version (history is never rewritten)."""
    if not reason:
        raise BusinessError("A reason is required", "reason_required")
    model = model_for_table(entity_type)
    versions = {r["version_number"]: r for r in entity_versions(entity_type, entity_id, tenant_id, True)}
    target = versions.get(int(version))
    if not target or not target["current_data"]:
        raise BusinessError("Version not restorable", "version_not_found", status_code=404)
    qs = model.objects.select_for_update().filter(pk=entity_id)
    if tenant_id and "tenant_id" in [f.attname for f in model._meta.concrete_fields]:
        qs = qs.filter(tenant_id=tenant_id)
    obj = qs.first()
    if not obj:
        raise BusinessError("Entity not found", "not_found", status_code=404)
    fields = {f.attname for f in model._meta.concrete_fields} - META_FIELDS - set(getattr(model, "SECRET_FIELDS", ()))
    changes = {k: v for k, v in target["current_data"].items() if k in fields}
    return audited_update(obj, changes, action=f"{entity_type}.restored", module="history",
                          reason=f"restore v{version}: {reason}", description=f"Restored version {version}: {reason}")


def trace(correlation_id: str, tenant_id: str | None) -> dict:
    cid = parse_uuid(correlation_id)
    if not cid:
        raise BusinessError("Invalid correlation id", "invalid_filter")
    t = " AND tenant_id = %s" if tenant_id else ""
    a = [cid] + ([tenant_id] if tenant_id else [])
    return {
        "correlation_id": cid,
        "audit_events": fetch_all_dict(f"SELECT id, created_at, actor_type, action, module, entity_type, entity_id, status, request_id FROM public.audit_events WHERE correlation_id = %s{t} ORDER BY created_at", a),
        "activity_events": fetch_all_dict(f"SELECT id, created_at, event_type, module, entity_type, entity_id, description FROM public.activity_events WHERE correlation_id = %s{t} ORDER BY created_at", a),
        "entity_history": fetch_all_dict(f"SELECT id, created_at, entity_type, entity_id, version_number, operation, changed_fields FROM public.entity_history WHERE correlation_id = %s{t} ORDER BY created_at", a),
        "executions": fetch_all_dict(f"SELECT id, created_at, module, operation, execution_id, celery_task_id, status, duration_ms, error_code, cost_cents FROM public.execution_logs WHERE correlation_id = %s{t} ORDER BY created_at", a),
    }
