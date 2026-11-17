"""AI Content Factory + Page Builder + CMS publication.

Every generation stores prompt template/version, provider, model, tokens, cost (if priced) and creates a
content version; manual edits and restores create new versions; publication requires the growth gate."""
from __future__ import annotations

import html
import json
import re
from base64 import b64encode

import requests
from django.db import transaction

from apps.ai_providers.gateway import complete
from apps.audit.services import record_activity, record_audit
from apps.core.context import get_context
from apps.core.db import fetch_all_dict, fetch_one
from apps.core.exceptions import BusinessError
from apps.integrations.gateway import get_credentials, http, load_account
from apps.licensing.services import check_quota
from apps.permissions.growth import gate, register

PROMPT_VERSION = "content-builtin-v1"
OPERATIONS = {
    "generate": "Write the requested content from scratch.",
    "rewrite": "Rewrite the content below, keeping meaning and facts.",
    "correct": "Fix grammar, spelling and style without changing meaning.",
    "translate": "Translate the content below into the target language, keeping formatting.",
    "optimize_seo": "Optimise the content below for the target keyword (title, headings, intro, internal structure) without keyword stuffing.",
    "optimize_geo": "Optimise the content below to be quotable by AI assistants: direct answers, definitions, FAQ section, explicit sources.",
}


def product_context(product_id: str | None) -> str:
    if not product_id:
        return "No product context."
    row = fetch_one("SELECT p.name, p.description, c.facts FROM public.products p LEFT JOIN public.product_business_context c ON c.product_id = p.id AND c.deleted_at IS NULL WHERE p.id = %s", [product_id])
    if not row:
        return "No product context."
    facts = [f for f in (row[2] or []) if f.get("status") in ("confirmed", "detected")]
    return json.dumps({"product": row[0], "description": row[1], "facts": [{"field": f["field"], "value": f["value"], "status": f["status"]} for f in facts]},
                      ensure_ascii=False)[:6000]


def _template(code: str | None) -> tuple[str, str]:
    if code:
        row = fetch_one("""SELECT template, coalesce(model_code, ''), updated_at FROM public.ai_prompt_templates
                            WHERE code = %s AND status = 'active' AND (tenant_id = %s OR tenant_id IS NULL) AND deleted_at IS NULL
                            ORDER BY tenant_id NULLS LAST LIMIT 1""", [code, get_context().tenant_id])
        if row:
            v = fetch_one("SELECT version_number FROM public.ai_prompt_templates WHERE code = %s ORDER BY tenant_id NULLS LAST LIMIT 1", [code])
            return row[0], f"{code}-v{v[0]}"
    return ("You are a senior content strategist. Use ONLY the product facts provided; never invent features, prices, customers or "
            "statistics. When information is missing, insert a placeholder like [À VÉRIFIER: ...]. Output Markdown."), PROMPT_VERSION


def create_version(content_id: str, title: str | None, body: str, source: str, model: str | None = None, prompt_version: str | None = None,
                   note: str | None = None) -> int:
    tid = get_context().tenant_id
    v = (fetch_one("SELECT coalesce(max(version), 0) FROM public.content_versions WHERE content_id = %s", [content_id])[0] or 0) + 1
    fetch_one("""INSERT INTO public.content_versions (tenant_id, content_id, version, title, body, change_note, source, model_code, prompt_version, author_id)
                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
              [tid, content_id, v, title, body, note, source, model, prompt_version, get_context().user_id])
    return v


def generate(content_id: str, operation: str = "generate", brief: str = "", target_language: str | None = None) -> dict:
    tid = get_context().tenant_id
    c = fetch_one("""SELECT id, title, body, content_type, language, product_id, keyword, objective, channel, prompt_template_code
                       FROM public.generated_contents WHERE id = %s AND tenant_id = %s AND deleted_at IS NULL""", [content_id, tid])
    if not c:
        raise BusinessError("content not found", "not_found", status_code=404)
    if operation not in OPERATIONS:
        raise BusinessError("unknown operation", "invalid")
    check_quota(tid, "content.generations.monthly")
    job = fetch_one("""INSERT INTO public.content_generation_jobs (tenant_id, content_id, status, execution_id) VALUES (%s,%s,'running',%s) RETURNING id""",
                    [tid, content_id, get_context().execution_id])[0]
    system, pversion = _template(c[9])
    user = (f"Task: {OPERATIONS[operation]}\nFormat: {c[3]}\nLanguage: {target_language or c[4]}\nTitle: {c[1]}\n"
            f"Target keyword: {c[6] or '-'}\nObjective: {c[7] or '-'}\nChannel: {c[8] or '-'}\nBrief: {brief or '-'}\n"
            f"Product facts (JSON, authoritative): {product_context(str(c[5]) if c[5] else None)}\n")
    if operation != "generate" and c[2]:
        user += f"\nContent to process:\n{c[2]}"
    try:
        r = complete("content.generate", [{"role": "user", "content": user}], system=system, max_tokens=3500,
                     product_id=str(c[5]) if c[5] else None, agent_code="content_writer", prompt_version=pversion)
    except BusinessError as e:
        fetch_one("UPDATE public.content_generation_jobs SET status = 'failed', error_message = %s WHERE id = %s RETURNING 1", [e.message, job])
        raise
    with transaction.atomic():
        v = create_version(content_id, c[1], r.text, "translation" if operation == "translate" else "optimization" if operation.startswith("optimize") else "ai",
                           r.model, pversion, operation)
        fetch_one("""UPDATE public.generated_contents SET body = %s, model_code = %s, provider_code = %s, prompt_version = %s,
                       cost_cents = coalesce(cost_cents, 0) + coalesce(%s, 0), agent_code = 'content_writer', language = coalesce(%s, language)
                     WHERE id = %s RETURNING 1""", [r.text, r.model, r.provider, pversion, r.cost_cents, target_language, content_id])
        fetch_one("UPDATE public.content_generation_jobs SET status = 'succeeded', model_code = %s WHERE id = %s RETURNING 1", [r.model, job])
        scores = score_content(content_id)
    record_activity(f"content.{operation}", "content", entity_type="generated_contents", entity_id=content_id, product_id=str(c[5]) if c[5] else None,
                    description=f"{operation} v{v}", metadata={"model": r.model, "cost_cents": float(r.cost_cents) if r.cost_cents is not None else None})
    return {"version": v, "model": r.model, "provider": r.provider, **scores}


def score_content(content_id: str) -> dict:
    """Deterministic, explainable on-page checks (not a ranking prediction)."""
    title, body, kw = fetch_one("SELECT title, coalesce(body,''), lower(coalesce(keyword,'')) FROM public.generated_contents WHERE id = %s", [content_id])
    text, low = body, body.lower()
    words = len(re.findall(r"\w+", text))
    heads = re.findall(r"(?m)^#{2,3} ", text)
    seo_checks = {"keyword_in_title": bool(kw) and kw in (title or "").lower(), "keyword_in_intro": bool(kw) and kw in low[:600],
                  "length_ok": words >= 600, "has_subheadings": len(heads) >= 2, "has_links": "](" in text}
    geo_checks = {"faq_section": bool(re.search(r"(?im)^#{2,3}.*(faq|questions)", text)), "direct_answers": bool(re.search(r"(?m)^\*\*.+\?\*\*|^#{3} .+\?", text)),
                  "sources_cited": bool(re.search(r"https?://", text)), "definitions": " est " in low or " is a " in low,
                  "no_unverified_placeholders": "[à vérifier" not in low}
    seo = round(100 * sum(seo_checks.values()) / len(seo_checks), 1)
    geo = round(100 * sum(geo_checks.values()) / len(geo_checks), 1)
    fetch_one("UPDATE public.generated_contents SET seo_score = %s, geo_score = %s WHERE id = %s RETURNING 1", [seo, geo, content_id])
    return {"seo_score": seo, "geo_score": geo, "seo_checks": seo_checks, "geo_checks": geo_checks, "words": words}


def verify_sources(content_id: str) -> list[dict]:
    body = fetch_one("SELECT coalesce(body,'') FROM public.generated_contents WHERE id = %s AND tenant_id = %s", [content_id, get_context().tenant_id])[0]
    out = []
    for u in dict.fromkeys(re.findall(r"https?://[^\s)\]>\"']+", body)):
        try:
            st = requests.head(u, timeout=10, allow_redirects=True).status_code
        except requests.RequestException as e:
            st = type(e).__name__
        out.append({"url": u, "status": st, "reachable": isinstance(st, int) and st < 400})
    fetch_one("UPDATE public.generated_contents SET sources = %s::jsonb WHERE id = %s RETURNING 1", [json.dumps(out), content_id])
    return out


TRANSITIONS = {"submit": ("draft", "review"), "approve": ("review", "approved"), "reject": ("review", "draft"), "archive": (None, "archived")}


def transition(content_id: str, op: str, comment: str = "") -> str:
    frm, to = TRANSITIONS[op]
    tid = get_context().tenant_id
    with transaction.atomic():
        cur = fetch_one("SELECT status FROM public.generated_contents WHERE id = %s AND tenant_id = %s FOR UPDATE", [content_id, tid])
        if not cur or (frm and cur[0] != frm):
            raise BusinessError(f"Invalid transition from {cur and cur[0]}", "invalid_state", status_code=409)
        fetch_one("UPDATE public.generated_contents SET status = %s WHERE id = %s RETURNING 1", [to, content_id])
        if op in ("approve", "reject"):
            fetch_one("INSERT INTO public.content_approvals (tenant_id, content_id, reviewer_id, decision, comment) VALUES (%s,%s,%s,%s,%s) RETURNING id",
                      [tid, content_id, get_context().user_id, "approved" if op == "approve" else "changes_requested", comment])
        record_audit(f"content.{op}", "content", entity_type="generated_contents", entity_id=content_id, description=comment)
    return to


# ───────────── CMS publication ─────────────
def md_to_html(md: str) -> str:
    out, para = [], []
    for line in md.splitlines():
        m = re.match(r"^(#{1,6}) (.*)", line)
        if m:
            if para:
                out.append(f"<p>{' '.join(para)}</p>")
                para = []
            out.append(f"<h{len(m.group(1))}>{html.escape(m.group(2))}</h{len(m.group(1))}>")
        elif line.strip().startswith(("- ", "* ")):
            out.append(f"<li>{html.escape(line.strip()[2:])}</li>")
        elif not line.strip():
            if para:
                out.append(f"<p>{' '.join(para)}</p>")
                para = []
        else:
            para.append(html.escape(line.strip()))
    if para:
        out.append(f"<p>{' '.join(para)}</p>")
    h = "\n".join(out)
    h = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", h)
    return re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', h)


def cms_publish(account_id: str, kind: str, title: str, html_body: str, slug: str | None, external_id: str | None, status: str = "publish") -> tuple[str, str]:
    acc = load_account(account_id)
    if acc.tenant_id != get_context().tenant_id:
        raise BusinessError("connector not found", "not_found", status_code=404)
    cred = get_credentials(acc.id)
    site = acc.settings.get("site_url", "").rstrip("/")
    if acc.provider == "wordpress":
        auth = {"Authorization": "Basic " + b64encode(f"{cred['username']}:{cred['application_password']}".encode()).decode()}
        url = f"{site}/wp-json/wp/v2/{'pages' if kind == 'page' else 'posts'}" + (f"/{external_id}" if external_id else "")
        d = http("POST", url, provider="wordpress", operation=f"publish_{kind}", account_id=acc.id, headers=auth,
                 json={"title": title, "content": html_body, "status": status, **({"slug": slug} if slug else {})}).json()
        return str(d["id"]), d.get("link", "")
    if acc.provider == "ghost":
        from apps.integrations.providers import _t_ghost  # noqa: F401  (same JWT scheme)
        import jwt as pyjwt
        from django.utils import timezone
        kid, secret = cred["admin_api_key"].split(":")
        iat = int(timezone.now().timestamp())
        tok = pyjwt.encode({"iat": iat, "exp": iat + 300, "aud": "/admin/"}, bytes.fromhex(secret), algorithm="HS256", headers={"kid": kid})
        res = "pages" if kind == "page" else "posts"
        d = http("POST", f"{site}/ghost/api/admin/{res}/?source=html", provider="ghost", operation=f"publish_{kind}", account_id=acc.id,
                 headers={"Authorization": f"Ghost {tok}"}, json={res: [{"title": title, "html": html_body, "status": "published" if status == "publish" else "draft"}]}).json()
        item = d[res][0]
        return str(item["id"]), item.get("url", "")
    if acc.provider == "rest_cms":
        d = http("POST", acc.settings["publish_url"], provider="rest_cms", operation=f"publish_{kind}", account_id=acc.id,
                 headers={"Authorization": f"Bearer {cred['api_key']}"}, json={"kind": kind, "title": title, "html": html_body, "slug": slug}).json()
        return str(d.get("id", "")), d.get("url", "")
    raise BusinessError(f"CMS {acc.provider} not supported yet", "not_implemented", status_code=501)


def request_publication(content_id: str, account_id: str) -> dict:
    c = fetch_one("SELECT status, product_id, title FROM public.generated_contents WHERE id = %s AND tenant_id = %s", [content_id, get_context().tenant_id])
    if not c:
        raise BusinessError("content not found", "not_found", status_code=404)
    if c[0] != "approved":
        raise BusinessError("Content must be approved before publication", "not_approved", status_code=409)
    decision, approval = gate("content", "publish", entity_type="generated_contents", entity_id=content_id,
                              payload={"account_id": account_id}, product_id=c[1])
    if decision == "execute":
        return publish_content({"entity_id": content_id, "payload": {"account_id": account_id}})
    return {"status": decision, "approval_id": approval}


@register("content", "publish")
def publish_content(approval: dict) -> dict:
    cid, account_id = approval["entity_id"], approval["payload"]["account_id"]
    tid = get_context().tenant_id
    title, body, ext = fetch_one("SELECT title, coalesce(body,''), (SELECT external_id FROM public.content_publications WHERE content_id = %s AND status = 'published' ORDER BY created_at DESC LIMIT 1) FROM public.generated_contents WHERE id = %s",
                                 [cid, cid])
    pub = fetch_one("INSERT INTO public.content_publications (tenant_id, content_id, channel, status, connector_account_id) VALUES (%s,%s,'cms','scheduled',%s) RETURNING id",
                    [tid, cid, account_id])[0]
    try:
        external_id, url = cms_publish(account_id, "post", title, md_to_html(body), None, ext)
    except BusinessError as e:
        fetch_one("UPDATE public.content_publications SET status = 'failed', error_message = %s WHERE id = %s RETURNING 1", [e.message, pub])
        from apps.notifications.service import notify
        notify("publication.failed", {"title": title, "error": e.message}, permission="content.publish")
        raise
    fetch_one("UPDATE public.content_publications SET status = 'published', external_id = %s, external_url = %s, published_at = now() WHERE id = %s RETURNING 1",
              [external_id, url, pub])
    fetch_one("UPDATE public.generated_contents SET status = 'published', published_url = %s WHERE id = %s RETURNING 1", [url, cid])
    record_audit("content.published", "content", entity_type="generated_contents", entity_id=cid, after={"url": url, "external_id": external_id})
    from apps.notifications.service import notify
    notify("publication.succeeded", {"title": title, "url": url}, permission="content.read")
    return {"status": "published", "url": url}


# ───────────── Page builder ─────────────
SECTION_TYPES = {"hero", "features", "text", "faq", "cta", "testimonials", "pricing", "comparison"}


def render_page(title: str, sections: list[dict], seo: dict) -> str:
    """Server-side HTML render with escaping (no user HTML is trusted)."""
    e = html.escape
    parts = [f"<title>{e(seo.get('title') or title)}</title>", f'<meta name="description" content="{e(seo.get("description", ""))}">']
    body = []
    faq_items = []
    for s in sections:
        t, p = s.get("type"), s.get("props", {})
        if t not in SECTION_TYPES:
            continue
        if t == "hero":
            body.append(f'<section class="hero"><h1>{e(p.get("headline", title))}</h1><p>{e(p.get("subheadline", ""))}</p>'
                        + (f'<a class="cta" href="{e(p["cta_url"])}">{e(p.get("cta_label", ""))}</a>' if p.get("cta_url", "").startswith(("https://", "/")) else "") + "</section>")
        elif t in ("features", "testimonials", "pricing", "comparison"):
            items = "".join(f"<li><h3>{e(i.get('title', ''))}</h3><p>{e(i.get('text', ''))}</p></li>" for i in p.get("items", []))
            body.append(f'<section class="{t}"><h2>{e(p.get("title", ""))}</h2><ul>{items}</ul></section>')
        elif t == "faq":
            faq_items += p.get("items", [])
            items = "".join(f"<details><summary>{e(i.get('q', ''))}</summary><p>{e(i.get('a', ''))}</p></details>" for i in p.get("items", []))
            body.append(f'<section class="faq"><h2>{e(p.get("title", "FAQ"))}</h2>{items}</section>')
        elif t == "text":
            body.append(f'<section class="text">{md_to_html(p.get("markdown", ""))}</section>')
        elif t == "cta":
            body.append(f'<section class="cta"><h2>{e(p.get("title", ""))}</h2></section>')
    if faq_items:
        ld = {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
            {"@type": "Question", "name": i.get("q", ""), "acceptedAnswer": {"@type": "Answer", "text": i.get("a", "")}} for i in faq_items]}
        parts.append(f'<script type="application/ld+json">{html.escape(json.dumps(ld, ensure_ascii=False), quote=False)}</script>')
    return ("<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            + "".join(parts) + "</head><body>" + "".join(body) + "</body></html>")


def save_page_version(page_id: str) -> int:
    tid = get_context().tenant_id
    title, sections, seo = fetch_one("SELECT title, sections, seo FROM public.builder_pages WHERE id = %s AND tenant_id = %s", [page_id, tid])
    v = (fetch_one("SELECT coalesce(max(version),0) FROM public.builder_page_versions WHERE page_id = %s", [page_id])[0] or 0) + 1
    fetch_one("""INSERT INTO public.builder_page_versions (tenant_id, page_id, version, title, sections, seo, author_id)
                 VALUES (%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s) RETURNING id""", [tid, page_id, v, title, json.dumps(sections), json.dumps(seo), get_context().user_id])
    return v


@register("pages", "publish")
def publish_page(approval: dict) -> dict:
    pid = approval["entity_id"]
    title, slug, sections, seo, account, ext, status = fetch_one(
        "SELECT title, slug, sections, seo, connector_account_id, external_id, status FROM public.builder_pages WHERE id = %s AND tenant_id = %s",
        [pid, get_context().tenant_id])
    if not account:
        raise BusinessError("No CMS connector selected for this page", "connector_required")
    full = render_page(title, sections, seo)
    body = full.split("<body>", 1)[1].rsplit("</body>", 1)[0]
    external_id, url = cms_publish(str(account), "page", title, body, slug, ext)
    fetch_one("UPDATE public.builder_pages SET status = 'published', external_id = %s, published_url = %s WHERE id = %s RETURNING 1", [external_id, url, pid])
    record_audit("page.published", "content", entity_type="builder_pages", entity_id=pid, after={"url": url})
    return {"status": "published", "url": url}


def request_page_publication(page_id: str) -> dict:
    st = fetch_one("SELECT status, product_id FROM public.builder_pages WHERE id = %s AND tenant_id = %s", [page_id, get_context().tenant_id])
    if not st or st[0] != "approved":
        raise BusinessError("Page must be approved before publication", "not_approved", status_code=409)
    decision, approval = gate("pages", "publish", entity_type="builder_pages", entity_id=page_id, payload={}, product_id=st[1])
    return publish_page({"entity_id": page_id}) if decision == "execute" else {"status": decision, "approval_id": approval}


def page_versions(page_id: str) -> list[dict]:
    return fetch_all_dict("SELECT version, title, sections, seo, author_id, created_at FROM public.builder_page_versions WHERE page_id = %s AND tenant_id = %s ORDER BY version DESC",
                          [page_id, get_context().tenant_id])
