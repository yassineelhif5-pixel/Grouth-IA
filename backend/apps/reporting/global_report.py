"""Global tenant reporting: module status (last/next run, duration, result, errors, cost) + KPIs, exports PDF/XLSX/CSV
persisted in private Storage with export_jobs / report_exports history."""
from __future__ import annotations

import csv
import io
import json

from apps.audit.services import record_audit
from apps.core.context import get_context
from apps.core.db import fetch_all_dict, fetch_one

MODULES = ["seo", "geo", "content", "pages", "social", "video", "opportunities", "prospects", "email_center", "whatsapp", "crm", "scheduler",
           "workflows", "intelligence", "thor", "integrations"]


def dashboard(days: int = 30) -> dict:
    tid = get_context().tenant_id
    status = fetch_all_dict("""
        SELECT m AS module,
               (SELECT row_to_json(x) FROM (SELECT created_at, status, duration_ms, error_message, operation FROM public.execution_logs e
                  WHERE e.tenant_id = %(t)s AND e.module = m ORDER BY created_at DESC LIMIT 1) x) AS last_execution,
               (SELECT count(*) FROM public.execution_logs e WHERE e.tenant_id = %(t)s AND e.module = m AND e.status = 'failed' AND e.created_at > now() - make_interval(days => %(d)s)) AS errors,
               (SELECT count(*) FROM public.execution_logs e WHERE e.tenant_id = %(t)s AND e.module = m AND e.created_at > now() - make_interval(days => %(d)s)) AS executions
          FROM unnest(%(mods)s::text[]) m""", {"t": tid, "d": days, "mods": MODULES})
    nxt = {r["category"]: r for r in fetch_all_dict("""SELECT category, min(next_run_at) AS next_run, max(last_run_at) AS last_run FROM public.tenant_schedulers
                                                        WHERE tenant_id = %s AND status = 'active' AND deleted_at IS NULL GROUP BY category""", [tid])}
    ai = fetch_all_dict("""SELECT feature_code, count(*) AS calls, sum(input_tokens) AS input_tokens, sum(output_tokens) AS output_tokens, sum(cost_cents) AS cost_cents
                            FROM public.ai_execution_logs WHERE tenant_id = %s AND created_at > now() - make_interval(days => %s) GROUP BY feature_code""", [tid, days])
    from apps.intelligence.engine import observe
    from apps.licensing.services import license_summary
    return {"window_days": days, "modules": status, "schedules": nxt, "ai_usage": ai, "kpis": observe(), "license": license_summary(tid),
            "revenue": {"note": "available once a payment/CRM revenue source is connected", "won_amount_cents":
                        fetch_one("""SELECT sum(o.amount_cents) FROM public.crm_opportunities o JOIN public.crm_pipeline_stages s ON s.id = o.stage_id
                                      WHERE o.tenant_id = %s AND s.is_won""", [tid])[0]}}


def _rows(d: dict) -> list[list]:
    rows = [["section", "key", "value"]]
    rows += [["kpi", k, v] for k, v in d["kpis"].items()]
    rows += [["module", m["module"], json.dumps({"executions": m["executions"], "errors": m["errors"], "last": m["last_execution"]}, default=str)] for m in d["modules"]]
    rows += [["ai", a["feature_code"], json.dumps(a, default=str)] for a in d["ai_usage"]]
    rows += [["quota", q["quota_code"], f"{q['used']}/{q['effective_limit']}"] for q in d["license"]["quotas"]]
    return rows


def render(fmt: str, d: dict) -> tuple[bytes, str]:
    rows = _rows(d)
    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        for r in rows:
            w.writerow(["'" + str(c) if str(c)[:1] in "=+-@" else c for c in r])
        return buf.getvalue().encode(), "text/csv"
    if fmt == "xlsx":
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "Growth IA"
        for r in rows:
            ws.append([str(c) if c is not None else "" for c in r])
        out = io.BytesIO()
        wb.save(out)
        return out.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table
    out = io.BytesIO()
    doc = SimpleDocTemplate(out, pagesize=A4, title="Growth IA report")
    st = getSampleStyleSheet()
    story = [Paragraph("Growth IA — rapport global", st["Title"]), Paragraph(f"Fenêtre : {d['window_days']} jours", st["Normal"]), Spacer(1, 12),
             Table([[str(c)[:60] if c is not None else "" for c in r] for r in rows], repeatRows=1)]
    doc.build(story)
    return out.getvalue(), "application/pdf"


def build_export(fmt: str = "pdf", days: int = 30) -> dict:
    tid = get_context().tenant_id
    d = dashboard(int(days))
    data, ctype = render(fmt, d)
    job = fetch_one("""INSERT INTO public.export_jobs (tenant_id, requested_by, export_type, scope, format, status) VALUES (%s,%s,'global_report',%s::jsonb,%s,'running')
                       RETURNING id""", [tid, get_context().user_id, json.dumps({"days": days}), fmt if fmt != "xlsx" else "xlsx"])[0]
    path = None
    try:
        from apps.core.storage import upload
        path = upload("exports", f"{tid}/reports/{job}.{fmt}", data, ctype)
        status = "succeeded"
    except Exception as e:  # noqa: BLE001 — storage not configured: file returned directly, still recorded
        status = "succeeded"
        _ = e
    fetch_one("""UPDATE public.export_jobs SET status = %s, storage_path = %s, link_expires_at = now() + interval '1 day', result = %s::jsonb WHERE id = %s RETURNING 1""",
              [status, path, json.dumps({"bytes": len(data), "stored": bool(path)}), job])
    snap = fetch_one("INSERT INTO public.tenant_reporting_snapshots (tenant_id, period_start, period_end, metrics) VALUES (%s, (now() - make_interval(days => %s))::date, now()::date, %s::jsonb) RETURNING id",
                     [tid, days, json.dumps(d["kpis"])])[0]
    fetch_one("INSERT INTO public.report_exports (tenant_id, export_job_id, format, storage_path) VALUES (%s,%s,%s,%s) RETURNING id",
              [tid, job, fmt if fmt in ("pdf", "csv", "xlsx") else "html", path])
    record_audit("report.exported", "reporting", entity_type="export_jobs", entity_id=job, after={"format": fmt, "bytes": len(data)})
    return {"export_job_id": str(job), "snapshot_id": str(snap), "storage_path": path, "bytes": len(data), "_data": data, "_ctype": ctype}
