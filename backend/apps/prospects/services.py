"""Smart Prospect: ICP, explainable qualification, segments, campaigns & sequences with consent and suppression checks."""
from __future__ import annotations

import csv
import io
import json
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.audit.services import record_activity, record_audit
from apps.core.context import get_context
from apps.core.db import fetch_all_dict, fetch_one
from apps.core.exceptions import BusinessError
from apps.licensing.services import check_quota
from apps.permissions.growth import gate, register

SIZE_BUCKETS = {"1-10": (1, 10), "11-50": (11, 50), "51-200": (51, 200), "201-1000": (201, 1000), "1000+": (1001, 10**9)}


def qualify(prospect_id: str) -> dict:
    """Explainable score vs the project ICP. Unknown data lowers confidence, it never adds points."""
    tid = get_context().tenant_id
    p = fetch_one("""SELECT p.id, coalesce(pp.icp, '{}'), c.industry, c.size_employees, c.country_code, coalesce(c.technologies,'{}'),
                            (SELECT job_title FROM public.prospect_contacts pc WHERE pc.prospect_id = p.id AND pc.deleted_at IS NULL LIMIT 1), p.need_detected
                       FROM public.prospects p LEFT JOIN public.prospect_projects pp ON pp.id = p.project_id
                       LEFT JOIN public.prospect_companies c ON c.id = p.company_id WHERE p.id = %s AND p.tenant_id = %s""", [prospect_id, tid])
    if not p:
        raise BusinessError("prospect not found", "not_found", status_code=404)
    _, icp, industry, size, country, techs, title, need = p
    factors, known, total = [], 0, 0

    def check(name, weight, ok, available):
        nonlocal known, total
        total += weight
        if available:
            known += weight
        factors.append({"factor": name, "weight": weight, "match": bool(ok) if available else None, "available": available})
        return weight if (available and ok) else 0
    pts = 0
    if icp.get("industries"):
        pts += check("industry", 25, industry and industry.lower() in [i.lower() for i in icp["industries"]], bool(industry))
    if icp.get("company_sizes"):
        rng = [SIZE_BUCKETS.get(b) for b in icp["company_sizes"] if b in SIZE_BUCKETS]
        pts += check("company_size", 20, size and any(lo <= size <= hi for lo, hi in rng), size is not None)
    if icp.get("countries"):
        pts += check("country", 15, country and country.upper() in [c.upper() for c in icp["countries"]], bool(country))
    if icp.get("functions"):
        pts += check("function", 20, title and any(f.lower() in title.lower() for f in icp["functions"]), bool(title))
    if icp.get("technologies"):
        pts += check("technology", 10, bool(set(t.lower() for t in techs) & set(t.lower() for t in icp["technologies"])), bool(techs))
    pts += check("need_detected", 10, bool(need), True)
    score = round(100 * pts / total, 1) if total else None
    confidence = round(100 * known / total, 1) if total else 0
    with transaction.atomic():
        fetch_one("UPDATE public.prospects SET score = %s, confidence = %s WHERE id = %s RETURNING 1", [score, confidence, prospect_id])
        fetch_one("INSERT INTO public.prospect_scores (tenant_id, prospect_id, score, model_version, factors) VALUES (%s,%s,%s,'icp-rules-v1',%s::jsonb) RETURNING id",
                  [tid, prospect_id, score or 0, json.dumps(factors)])
        if score is not None and score >= 70 and confidence >= 60:
            st = fetch_one("SELECT status FROM public.prospects WHERE id = %s", [prospect_id])[0]
            if st in ("new", "new_lead", "enriched"):
                fetch_one("UPDATE public.prospects SET status = 'qualified' WHERE id = %s RETURNING 1", [prospect_id])
                from apps.notifications.service import notify
                notify("prospect.qualified", {"name": prospect_id[:8], "score": score}, permission="prospects.read")
    return {"score": score, "confidence": confidence, "factors": factors}


def import_csv(project_id: str | None, content: str, source_label: str) -> dict:
    """Columns: company, domain, industry, size_employees, country, first_name, last_name, email, job_title, consent_status."""
    tid = get_context().tenant_id
    rows = list(csv.DictReader(io.StringIO(content)))
    check_quota(tid, "prospects.max", len(rows))
    src = fetch_one("""INSERT INTO public.prospect_sources (tenant_id, name, source_type) VALUES (%s,%s,'import') RETURNING id""", [tid, source_label[:200]])[0]
    created = skipped = 0
    with transaction.atomic():
        for r in rows:
            email = (r.get("email") or "").strip().lower()
            if email and fetch_one("SELECT 1 FROM public.prospect_contacts WHERE tenant_id = %s AND lower(email) = %s AND deleted_at IS NULL", [tid, email]):
                skipped += 1
                continue
            comp = None
            if r.get("company"):
                comp = fetch_one("SELECT id FROM public.prospect_companies WHERE tenant_id = %s AND lower(name) = lower(%s) AND deleted_at IS NULL", [tid, r["company"]])
                comp = comp[0] if comp else fetch_one("""INSERT INTO public.prospect_companies (tenant_id, name, domain, industry, size_employees, country_code, source)
                                                        VALUES (%s,%s,%s,%s,%s,%s,'import') RETURNING id""",
                                                     [tid, r["company"], r.get("domain"), r.get("industry"), int(r["size_employees"]) if (r.get("size_employees") or "").isdigit() else None,
                                                      (r.get("country") or "")[:2].upper() or None])[0]
            pid = fetch_one("INSERT INTO public.prospects (tenant_id, project_id, company_id, source_id, status, source_detail) VALUES (%s,%s,%s,%s,'new_lead',%s) RETURNING id",
                            [tid, project_id, comp, src, source_label[:200]])[0]
            consent = r.get("consent_status") if r.get("consent_status") in ("legitimate_interest", "consented", "opted_out") else "unknown"
            fetch_one("""INSERT INTO public.prospect_contacts (tenant_id, prospect_id, first_name, last_name, email, job_title, consent_status)
                         VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""", [tid, pid, r.get("first_name"), r.get("last_name"), email or None, r.get("job_title"), consent])
            created += 1
    record_audit("prospects.imported", "prospects", entity_type="prospect_sources", entity_id=src, after={"created": created, "skipped_duplicates": skipped})
    return {"created": created, "skipped_duplicates": skipped}


def segment_members(segment_id: str) -> list[dict]:
    tid = get_context().tenant_id
    crit = fetch_one("SELECT criteria, project_id FROM public.prospect_segments WHERE id = %s AND tenant_id = %s", [segment_id, tid])
    if not crit:
        raise BusinessError("segment not found", "not_found", status_code=404)
    c, project = crit
    return fetch_all_dict("""SELECT pc.id AS contact_id, pc.email, pc.consent_status, p.id AS prospect_id, p.status, p.score
                               FROM public.prospects p JOIN public.prospect_contacts pc ON pc.prospect_id = p.id AND pc.deleted_at IS NULL
                               LEFT JOIN public.prospect_companies co ON co.id = p.company_id
                              WHERE p.tenant_id = %s AND p.deleted_at IS NULL AND (%s::uuid IS NULL OR p.project_id = %s::uuid)
                                AND (%s::numeric IS NULL OR p.score >= %s::numeric) AND (%s = '' OR p.status = %s)
                                AND (%s = '' OR co.industry ILIKE %s) AND (%s = '' OR co.country_code = %s)""",
                          [tid, project, project, c.get("min_score"), c.get("min_score"), c.get("status", ""), c.get("status", ""),
                           c.get("industry", ""), c.get("industry", ""), c.get("country", ""), c.get("country", "")])


def launch_campaign(campaign_id: str) -> dict:
    tid = get_context().tenant_id
    camp = fetch_one("SELECT segment_id, status, mailbox_id, channel FROM public.prospect_campaigns WHERE id = %s AND tenant_id = %s", [campaign_id, tid])
    if not camp:
        raise BusinessError("campaign not found", "not_found", status_code=404)
    if camp[1] not in ("draft", "paused"):
        raise BusinessError(f"Campaign is {camp[1]}", "invalid_state", status_code=409)
    if not fetch_one("SELECT 1 FROM public.prospect_campaign_sequences WHERE campaign_id = %s", [campaign_id]):
        raise BusinessError("Add at least one sequence step", "invalid")
    if camp[3] == "email" and not camp[2]:
        raise BusinessError("Select a sending mailbox", "invalid")
    decision, approval = gate("prospects", "send_campaign", entity_type="prospect_campaigns", entity_id=campaign_id, payload={})
    return activate({"entity_id": campaign_id}) if decision == "execute" else {"status": decision, "approval_id": approval}


@register("prospects", "send_campaign")
def activate(approval: dict) -> dict:
    cid = approval["entity_id"]
    tid = get_context().tenant_id
    seg = fetch_one("SELECT segment_id FROM public.prospect_campaigns WHERE id = %s", [cid])[0]
    added = excluded = 0
    with transaction.atomic():
        for m in segment_members(str(seg)) if seg else []:
            if not m["email"] or m["consent_status"] == "opted_out" or fetch_one(
                    "SELECT 1 FROM public.prospect_suppression_lists WHERE tenant_id = %s AND lower(email) = lower(%s) AND deleted_at IS NULL", [tid, m["email"]]):
                excluded += 1
                continue
            r = fetch_one("""INSERT INTO public.prospect_campaign_recipients (tenant_id, campaign_id, contact_id, status) VALUES (%s,%s,%s,'active')
                             ON CONFLICT (tenant_id, campaign_id, contact_id) WHERE deleted_at IS NULL DO NOTHING RETURNING id""", [tid, cid, m["contact_id"]])
            added += bool(r)
        fetch_one("UPDATE public.prospect_campaigns SET status = 'running' WHERE id = %s RETURNING 1", [cid])
    record_audit("campaign.launched", "prospects", entity_type="prospect_campaigns", entity_id=cid, after={"recipients": added, "excluded": excluded})
    return {"status": "running", "recipients": added, "excluded_no_consent_or_suppressed": excluded}


def render_template(body: str, ctx: dict) -> str:
    for k, v in ctx.items():
        body = body.replace("{{" + k + "}}", str(v or ""))
    return body


def process_campaign(campaign_id: str) -> dict:
    """Sends due sequence steps (one step per recipient per run). Stops on reply, unsubscribe, bounce, opt-out."""
    tid = get_context().tenant_id
    camp = fetch_one("SELECT mailbox_id, status, product_id FROM public.prospect_campaigns WHERE id = %s AND tenant_id = %s", [campaign_id, tid])
    if not camp or camp[1] != "running":
        return {"status": "not_running"}
    steps = fetch_all_dict("""SELECT s.id, s.step, s.delay_hours, t.subject, t.body FROM public.prospect_campaign_sequences s
                               JOIN public.prospect_templates t ON t.id = s.template_id WHERE s.campaign_id = %s ORDER BY s.step""", [campaign_id])
    sent = errors = 0
    from apps.email_center.services import send_email
    for r in fetch_all_dict("""SELECT r.id, r.current_step, pc.email, pc.first_name, pc.last_name, pc.consent_status, pc.prospect_id, co.name AS company,
                                      (SELECT max(m.sent_at) FROM public.prospect_messages m WHERE m.recipient_id = r.id) AS last_sent
                                 FROM public.prospect_campaign_recipients r JOIN public.prospect_contacts pc ON pc.id = r.contact_id
                                 LEFT JOIN public.prospects p ON p.id = pc.prospect_id LEFT JOIN public.prospect_companies co ON co.id = p.company_id
                                WHERE r.campaign_id = %s AND r.status = 'active' LIMIT 200""", [campaign_id]):
        if r["current_step"] >= len(steps):
            fetch_one("UPDATE public.prospect_campaign_recipients SET status = 'completed' WHERE id = %s RETURNING 1", [r["id"]])
            continue
        step = steps[r["current_step"]]
        if r["last_sent"] and r["last_sent"] + timedelta(hours=step["delay_hours"]) > timezone.now():
            continue
        if r["consent_status"] == "opted_out":
            fetch_one("UPDATE public.prospect_campaign_recipients SET status = 'unsubscribed' WHERE id = %s RETURNING 1", [r["id"]])
            continue
        ctx = {"first_name": r["first_name"], "last_name": r["last_name"], "company": r["company"]}
        msg = fetch_one("INSERT INTO public.prospect_messages (tenant_id, recipient_id, sequence_id, status, channel) VALUES (%s,%s,%s,'scheduled','email') RETURNING id",
                        [tid, r["id"], step["id"]])[0]
        try:
            conv = fetch_one("SELECT id FROM public.email_conversations WHERE campaign_id = %s AND prospect_id = %s ORDER BY created_at LIMIT 1", [campaign_id, r["prospect_id"]])
            mid = send_email(str(camp[0]), [r["email"]], render_template(step["subject"] or "", ctx), render_template(step["body"], ctx),
                             conversation_id=str(conv[0]) if conv else None, prospect_id=str(r["prospect_id"]), campaign_id=campaign_id,
                             product_id=str(camp[2]) if camp[2] else None)
            fetch_one("UPDATE public.prospect_messages SET status = 'sent', email_message_id = %s, sent_at = now() WHERE id = %s RETURNING 1", [mid, msg])
            fetch_one("UPDATE public.prospect_campaign_recipients SET current_step = current_step + 1 WHERE id = %s RETURNING 1", [r["id"]])
            fetch_one("UPDATE public.prospects SET status = CASE WHEN status IN ('new','new_lead','qualified','enriched') THEN 'contacted' ELSE status END WHERE id = %s RETURNING 1",
                      [r["prospect_id"]])
            sent += 1
        except BusinessError as e:
            fetch_one("UPDATE public.prospect_messages SET status = 'failed', error_message = %s WHERE id = %s RETURNING 1", [e.message, msg])
            errors += 1
            if e.code in ("quota_exceeded", "connector_not_configured"):
                break
    record_activity("campaign.processed", "prospects", entity_type="prospect_campaigns", entity_id=campaign_id, metadata={"sent": sent, "errors": errors})
    return {"sent": sent, "errors": errors}


def assign(prospect_id: str, user_id: str) -> None:
    tid = get_context().tenant_id
    fetch_one("UPDATE public.prospects SET owner_user_id = %s WHERE id = %s AND tenant_id = %s RETURNING 1", [user_id, prospect_id, tid])
    fetch_one("INSERT INTO public.prospect_commercial_assignments (tenant_id, prospect_id, user_id) VALUES (%s,%s,%s) RETURNING id", [tid, prospect_id, user_id])
    record_audit("prospect.assigned", "prospects", entity_type="prospects", entity_id=prospect_id, after={"user_id": user_id})
