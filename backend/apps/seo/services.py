from __future__ import annotations

from django.conf import settings
from django.db import transaction

from apps.audit.services import record_activity, record_audit
from apps.core.context import get_context
from apps.core.db import fetch_all_dict, fetch_one
from apps.core.exceptions import BusinessError
from apps.licensing.services import check_quota, effective_limit

from .crawler import RECOMMENDATIONS, Crawler


def launch_audit(project_id: str, audit_type: str = "full", pages_limit: int | None = None, website_id: str | None = None) -> str:
    ctx = get_context()
    proj = fetch_one("""SELECT p.id, p.product_id, coalesce(w.id, p.website_id), coalesce(w.url, pw.url, pr.primary_domain, pr.url)
                          FROM public.seo_projects p JOIN public.products pr ON pr.id = p.product_id
                          LEFT JOIN public.websites pw ON pw.id = p.website_id
                          LEFT JOIN public.websites w ON w.id = %s AND w.tenant_id = p.tenant_id
                         WHERE p.id = %s AND p.tenant_id = %s AND p.deleted_at IS NULL""", [website_id, project_id, ctx.tenant_id])
    if not proj or not proj[3]:
        raise BusinessError("SEO project not found or no website/domain configured", "not_found", status_code=404)
    check_quota(ctx.tenant_id, "seo.audits.monthly")
    cap = effective_limit(ctx.tenant_id, "seo.pages_per_audit") or settings.CRAWLER_MAX_PAGES
    limit = min(int(pages_limit or cap), cap, settings.CRAWLER_MAX_PAGES)
    aid = fetch_one("""INSERT INTO public.seo_audits (tenant_id, project_id, website_id, audit_type, pages_limit, status, requested_by, summary)
                       VALUES (%s,%s,%s,%s,%s,'queued',%s, jsonb_build_object('url', %s::text)) RETURNING id""",
                    [ctx.tenant_id, project_id, proj[2], audit_type, limit, ctx.user_id if ctx.actor_type in ("user", "pilot") else None, proj[3]])[0]
    record_audit("seo.audit_launched", "seo", entity_type="seo_audits", entity_id=aid, after={"url": proj[3], "pages_limit": limit})
    record_activity("seo.audit_launched", "seo", entity_type="seo_audits", entity_id=aid, product_id=str(proj[1]), description=f"Audit SEO {proj[3]}")
    from .tasks import run_audit
    transaction.on_commit(lambda: run_audit.delay_traced(str(aid)))
    return str(aid)


def execute_audit(audit_id: str) -> dict:
    row = fetch_one("""SELECT a.id, a.project_id, a.website_id, a.pages_limit, a.summary->>'url', p.product_id
                         FROM public.seo_audits a JOIN public.seo_projects p ON p.id = a.project_id WHERE a.id = %s""", [audit_id])
    if not row:
        raise BusinessError("audit not found", "not_found")
    _, project_id, website_id, limit, url, product_id = row
    tid = get_context().tenant_id
    fetch_one("UPDATE public.seo_audits SET status = 'running', started_at = now(), execution_id = %s WHERE id = %s RETURNING 1",
              [get_context().execution_id, audit_id])
    try:
        res = Crawler(settings.CRAWLER_USER_AGENT, max_pages=limit, delay=settings.CRAWLER_DELAY_SECONDS).crawl(url)
    except Exception as e:  # noqa: BLE001 — persisted then re-raised
        fetch_one("UPDATE public.seo_audits SET status = 'failed', completed_at = now(), error_message = %s WHERE id = %s RETURNING 1",
                  [str(e)[:1000], audit_id])
        raise
    page_ids: dict[str, str] = {}
    with transaction.atomic():
        for p in res.pages:
            wp = None
            if website_id:
                path = "/" + p.url.split("/", 3)[3] if p.url.count("/") >= 3 else "/"
                wp = fetch_one("""INSERT INTO public.website_pages (tenant_id, website_id, url, path, title, meta_description, status_code, last_crawled_at)
                                  VALUES (%s,%s,%s,%s,%s,%s,%s, now())
                                  ON CONFLICT (tenant_id, website_id, path) WHERE deleted_at IS NULL DO UPDATE SET title = EXCLUDED.title,
                                    meta_description = EXCLUDED.meta_description, status_code = EXCLUDED.status_code, last_crawled_at = now()
                                  RETURNING id""", [tid, website_id, p.url, path[:2000], p.title, p.meta_description, p.status_code])
            page_issues = [i for i in res.issues if i.page_url == p.url]
            page_score = max(0, 100 - sum({"critical": 30, "high": 15, "medium": 7, "low": 2, "info": 0}[i.severity] for i in page_issues))
            page_ids[p.url] = str(fetch_one("""INSERT INTO public.seo_audit_pages (tenant_id, audit_id, page_id, url, score, data, status_code, load_ms)
                                               VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s,%s) RETURNING id""",
                                            [tid, audit_id, wp[0] if wp else None, p.url, page_score,
                                             __import__("json").dumps(p.as_dict(), default=list), p.status_code, p.load_ms])[0])
        issue_ids: dict[str, list[str]] = {}
        for i in res.issues:
            iid = fetch_one("""INSERT INTO public.seo_issues (tenant_id, audit_id, audit_page_id, issue_code, severity, description, category, page_url, details, impact)
                               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s) RETURNING id""",
                            [tid, audit_id, page_ids.get(i.page_url or ""), i.code, i.severity, i.description, i.category, i.page_url,
                             __import__("json").dumps(i.details), i.impact])[0]
            issue_ids.setdefault(i.code, []).append(str(iid))
        for code, ids in issue_ids.items():
            if code in RECOMMENDATIONS:
                title, desc, prio, impact, diff = RECOMMENDATIONS[code]
                fetch_one("""INSERT INTO public.seo_recommendations (tenant_id, project_id, issue_id, audit_id, title, description, priority, impact,
                               difficulty, category, details) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb) RETURNING id""",
                          [tid, project_id, ids[0], audit_id, title, desc, prio, impact, diff, code,
                           __import__("json").dumps({"occurrences": len(ids)})])
        summary = {"url": url, "pages_crawled": len(res.pages), "blocked_by_robots": len(res.blocked_by_robots), "sitemap_urls": len(res.sitemap_urls),
                   "robots_txt": res.robots_txt is not None, "issues_by_severity": _count(res.issues, "severity"),
                   "issues_by_category": _count(res.issues, "category"), "duration_ms": res.duration_ms,
                   "core_web_vitals": "not_measured (PageSpeed connector not configured)"}
        fetch_one("""UPDATE public.seo_audits SET status = 'succeeded', completed_at = now(), score = %s, pages_analyzed = %s,
                       issues_count = %s, summary = %s::jsonb WHERE id = %s RETURNING 1""",
                  [res.score, len(res.pages), len(res.issues), __import__("json").dumps(summary), audit_id])
    record_audit("seo.audit_completed", "seo", entity_type="seo_audits", entity_id=audit_id, after={"score": res.score, "issues": len(res.issues)})
    record_activity("seo.audit_completed", "seo", entity_type="seo_audits", entity_id=audit_id, product_id=str(product_id),
                    description=f"Audit SEO terminé — score {res.score}")
    from apps.notifications.service import notify
    notify("report.ready", {"title": f"Audit SEO {url} — score {res.score}"}, permission="seo.read")
    return {"score": res.score, "pages": len(res.pages), "issues": len(res.issues)}


def _count(items, attr):
    out: dict[str, int] = {}
    for i in items:
        out[getattr(i, attr)] = out.get(getattr(i, attr), 0) + 1
    return out


def compare(audit_a: str, audit_b: str, tenant_id: str) -> dict:
    rows = {str(r["id"]): r for r in fetch_all_dict("""SELECT id, created_at, score, pages_analyzed, issues_count, summary FROM public.seo_audits
                                                        WHERE id IN (%s, %s) AND tenant_id = %s""", [audit_a, audit_b, tenant_id])}
    if len(rows) != 2:
        raise BusinessError("Audits not found", "not_found", status_code=404)
    def keys(aid):
        return {(r["issue_code"], r["page_url"]) for r in fetch_all_dict("SELECT issue_code, page_url FROM public.seo_issues WHERE audit_id = %s", [aid])}
    ka, kb = keys(audit_a), keys(audit_b)
    a, b = rows[audit_a], rows[audit_b]
    return {"from": a, "to": b, "score_delta": float(b["score"] or 0) - float(a["score"] or 0),
            "new_issues": [{"code": c, "page": p} for c, p in sorted(kb - ka, key=str)][:500],
            "resolved_issues": [{"code": c, "page": p} for c, p in sorted(ka - kb, key=str)][:500],
            "persisting": len(ka & kb)}
