"""GEO / AI search visibility. Observed facts only: answers are obtained through official APIs of the
configured engines (method=api_answer — this approximates but is NOT identical to the consumer apps),
mentions/citations are extracted from the text actually returned. Engines without an API (Copilot,
Google AI Overviews) are reported as not_available, never simulated."""
from __future__ import annotations

import json
import re
from urllib import robotparser
from urllib.parse import urlparse

import requests
from django.conf import settings
from django.db import transaction

from apps.ai_providers.gateway import AINotConfigured, complete
from apps.audit.services import record_activity, record_audit
from apps.core.context import get_context
from apps.core.db import fetch_all_dict, fetch_one
from apps.core.exceptions import BusinessError
from apps.licensing.services import check_quota

ENGINES = {"chatgpt": "geo.engine.openai", "claude": "geo.engine.anthropic", "gemini": "geo.engine.gemini",
           "perplexity": "geo.engine.perplexity", "mistral": "geo.engine.mistral"}
NOT_AVAILABLE = {"copilot": "no public answer API", "google_ai_overviews": "no public API"}
URL_RE = re.compile(r"https?://[^\s)\]>\"']+")


def _brands(product_id: str, extra: list[str] | None) -> list[dict]:
    rows = fetch_all_dict("""SELECT id, name, entity_type, coalesce(aliases, '{}') AS aliases FROM public.brand_entities
                              WHERE product_id = %s AND deleted_at IS NULL""", [product_id])
    if not any(r["entity_type"] == "brand" for r in rows):
        p = fetch_one("SELECT name FROM public.products WHERE id = %s", [product_id])
        rows.append({"id": None, "name": p[0], "entity_type": "brand", "aliases": []})
    rows += [{"id": None, "name": n, "entity_type": "competitor", "aliases": []} for n in (extra or [])]
    return rows


def extract(text: str, brands: list[dict]) -> tuple[list[dict], list[dict]]:
    mentions, low = [], text.lower()
    for b in brands:
        positions = [m.start() for n in [b["name"], *b["aliases"]] if n for m in re.finditer(rf"(?<!\w){re.escape(n.lower())}(?!\w)", low)]
        if positions:
            mentions.append({"brand": b, "first": min(positions), "count": len(positions)})
    mentions.sort(key=lambda m: m["first"])
    citations = []
    for i, u in enumerate(dict.fromkeys(u.rstrip(".,;") for u in URL_RE.findall(text))):
        citations.append({"url": u, "domain": urlparse(u).netloc.lower(), "position": i + 1})
    return mentions, citations


def run_query(query_id: str) -> dict:
    tid = get_context().tenant_id
    q = fetch_one("""SELECT id, product_id, query, coalesce(engines, ARRAY['chatgpt','claude','gemini','perplexity']), coalesce(competitor_names,'{}'),
                            locale FROM public.ai_search_queries WHERE id = %s AND tenant_id = %s AND deleted_at IS NULL""", [query_id, tid])
    if not q:
        raise BusinessError("query not found", "not_found", status_code=404)
    _, product_id, text, engines, competitors, locale = q
    brands = _brands(str(product_id), competitors)
    own = {urlparse(fetch_one("SELECT coalesce(url, 'https://' || primary_domain, '') FROM public.products WHERE id = %s", [product_id])[0] or "").netloc.lower()}
    out = {}
    for engine in engines:
        if engine in NOT_AVAILABLE:
            out[engine] = "not_available"
            continue
        check_quota(tid, "geo.queries.monthly")
        run_id = fetch_one("""INSERT INTO public.ai_search_runs (tenant_id, query_id, engine, status, method, execution_id)
                              VALUES (%s,%s,%s,'succeeded','api_answer',%s) RETURNING id""", [tid, query_id, engine, get_context().execution_id])[0]
        try:
            r = complete(ENGINES.get(engine, f"geo.engine.{engine}"), [{"role": "user", "content": text}],
                         system=f"Answer the user's question as you normally would. Language: {locale or 'auto'}. Cite sources as URLs when you use them.",
                         max_tokens=900, product_id=str(product_id), agent_code="geo_monitor", prompt_version="geo-answer-v1")
        except (AINotConfigured, BusinessError) as e:
            fetch_one("UPDATE public.ai_search_runs SET status = 'failed', error_message = %s WHERE id = %s RETURNING 1", [getattr(e, "message", str(e)), run_id])
            out[engine] = "not_configured" if isinstance(e, AINotConfigured) else "failed"
            continue
        with transaction.atomic():
            fetch_one("""UPDATE public.ai_search_runs SET provider_code = %s, model_code = %s, cost_cents = %s, duration_ms = %s WHERE id = %s RETURNING 1""",
                      [r.provider, r.model, r.cost_cents, r.duration_ms, run_id])
            resp_id = fetch_one("INSERT INTO public.ai_search_responses (tenant_id, run_id, response_text, raw) VALUES (%s,%s,%s,%s::jsonb) RETURNING id",
                                [tid, run_id, r.text, json.dumps({"input_tokens": r.input_tokens, "output_tokens": r.output_tokens})])[0]
            mentions, citations = extract(r.text, brands)
            for pos, m in enumerate(mentions, 1):
                fetch_one("""INSERT INTO public.ai_search_mentions (tenant_id, response_id, brand_entity_id, mention_text, position)
                             VALUES (%s,%s,%s,%s,%s) RETURNING id""", [tid, resp_id, m["brand"]["id"], m["brand"]["name"], pos])
            for c in citations:
                fetch_one("INSERT INTO public.ai_search_citations (tenant_id, response_id, url, domain, position) VALUES (%s,%s,%s,%s,%s) RETURNING id",
                          [tid, resp_id, c["url"][:2000], c["domain"], c["position"]])
        brand_names = {b["name"] for b in brands if b["entity_type"] == "brand"}
        out[engine] = {"brand_mentioned": any(m["brand"]["name"] in brand_names for m in mentions),
                       "mentions": [m["brand"]["name"] for m in mentions], "citations": len(citations),
                       "own_domain_cited": any(c["domain"] in own for c in citations)}
    record_activity("geo.query_run", "geo", entity_type="ai_search_queries", entity_id=query_id, product_id=str(product_id),
                    description=text[:200], metadata={"engines": list(out)})
    return out


def snapshot(product_id: str, days: int = 30, persist: bool = True) -> dict:
    """Visibility computed only from stored observations (no estimation)."""
    tid = get_context().tenant_id
    rows = fetch_all_dict("""SELECT r.engine, count(DISTINCT r.id) AS runs,
                                    count(DISTINCT r.id) FILTER (WHERE EXISTS (SELECT 1 FROM public.ai_search_mentions m
                                        JOIN public.ai_search_responses s ON s.id = m.response_id WHERE s.run_id = r.id AND m.position IS NOT NULL
                                        AND m.mention_text = (SELECT name FROM public.products WHERE id = %s))) AS runs_with_brand
                               FROM public.ai_search_runs r JOIN public.ai_search_queries q ON q.id = r.query_id
                              WHERE q.product_id = %s AND r.tenant_id = %s AND r.status = 'succeeded'
                                AND r.created_at > now() - make_interval(days => %s) GROUP BY r.engine""", [product_id, product_id, tid, days])
    data = {r["engine"]: {"runs": r["runs"], "runs_with_brand": r["runs_with_brand"],
                          "visibility_pct": round(100.0 * r["runs_with_brand"] / r["runs"], 1) if r["runs"] else None} for r in rows}
    total = sum(r["runs"] for r in rows)
    score = round(100.0 * sum(r["runs_with_brand"] for r in rows) / total, 1) if total else None
    if persist:
        fetch_one("""INSERT INTO public.ai_visibility_snapshots (tenant_id, product_id, visibility_score, data) VALUES (%s,%s,%s,%s::jsonb) RETURNING id""",
                  [tid, product_id, score, json.dumps({"window_days": days, "engines": data, "method": "api_answer"})])
    return {"visibility_score": score, "engines": data, "observations": total}


def geo_audit(product_id: str) -> str:
    """Crawler access per AI bot (robots.txt), llms.txt, structured data & FAQ coverage from the latest SEO crawl."""
    tid = get_context().tenant_id
    url = fetch_one("SELECT coalesce(url, 'https://' || primary_domain) FROM public.products WHERE id = %s AND tenant_id = %s", [product_id, tid])
    if not url or not url[0]:
        raise BusinessError("Product URL required", "url_required")
    root = f"{urlparse(url[0]).scheme}://{urlparse(url[0]).netloc}"
    aid = fetch_one("INSERT INTO public.geo_audits (tenant_id, product_id, status, started_at, execution_id) VALUES (%s,%s,'running', now(), %s) RETURNING id",
                    [tid, product_id, get_context().execution_id])[0]
    headers = {"User-Agent": settings.CRAWLER_USER_AGENT}
    try:
        robots = requests.get(f"{root}/robots.txt", timeout=15, headers=headers)
        llms = requests.get(f"{root}/llms.txt", timeout=15, headers=headers)
    except requests.RequestException as e:
        fetch_one("UPDATE public.geo_audits SET status = 'failed', error_message = %s, completed_at = now() WHERE id = %s RETURNING 1", [str(e)[:500], aid])
        raise BusinessError("Site unreachable", "unreachable", status_code=502) from e
    rp = robotparser.RobotFileParser()
    rp.parse(robots.text.splitlines() if robots.status_code == 200 else [])
    website = fetch_one("SELECT id FROM public.websites WHERE product_id = %s AND tenant_id = %s AND deleted_at IS NULL ORDER BY created_at LIMIT 1", [product_id, tid])
    crawlers = fetch_all_dict("SELECT id, code, name, user_agent_pattern, purpose FROM public.ai_crawler_registry ORDER BY code")
    access = {}
    for c in crawlers:
        allowed = rp.can_fetch(c["user_agent_pattern"], root + "/")
        access[c["name"]] = {"allowed": allowed, "purpose": c["purpose"]}
        if website:
            fetch_one("""INSERT INTO public.ai_crawler_checks (tenant_id, website_id, crawler_id, allowed, robots_rule) VALUES (%s,%s,%s,%s,%s) RETURNING id""",
                      [tid, website[0], c["id"], allowed, "robots.txt" if robots.status_code == 200 else "no robots.txt"])
    last = fetch_one("""SELECT a.id FROM public.seo_audits a JOIN public.seo_projects p ON p.id = a.project_id
                         WHERE p.product_id = %s AND a.status = 'succeeded' ORDER BY a.completed_at DESC LIMIT 1""", [product_id])
    pages = fetch_all_dict("SELECT url, data FROM public.seo_audit_pages WHERE audit_id = %s", [last[0]]) if last else []
    with_schema = sum(1 for p in pages if (p["data"] or {}).get("schema_types"))
    with_faq = sum(1 for p in pages if "FAQPage" in ((p["data"] or {}).get("schema_types") or []))
    recs = []
    blocked_search = [n for n, v in access.items() if not v["allowed"] and v["purpose"] in ("search", "user_fetch")]
    if blocked_search:
        recs.append(("Autoriser les robots de recherche IA", f"Bloqués : {', '.join(blocked_search)}. Ils alimentent les réponses citant des sources.", 1))
    if llms.status_code != 200:
        recs.append(("Publier un fichier /llms.txt", "Résumé structuré du site destiné aux assistants IA (proposition émergente, non standardisée).", 4))
    if pages and with_schema < len(pages) / 2:
        recs.append(("Étendre les données structurées", f"{with_schema}/{len(pages)} pages avec Schema.org.", 2))
    if pages and not with_faq:
        recs.append(("Ajouter des FAQ structurées", "Questions/réponses explicites (FAQPage) facilitent la citation.", 2))
    if not pages:
        recs.append(("Lancer un audit SEO", "Nécessaire pour analyser la structure des contenus.", 2))
    for title, desc, prio in recs:
        fetch_one("INSERT INTO public.geo_recommendations (tenant_id, product_id, audit_id, title, description, priority) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
                  [tid, product_id, aid, title, desc, prio])
    score = round(100 * (sum(1 for v in access.values() if v["allowed"]) / max(1, len(access))) * 0.4
                  + (100 * with_schema / len(pages) if pages else 0) * 0.4 + (20 if llms.status_code == 200 else 0), 1)
    fetch_one("""UPDATE public.geo_audits SET status = 'succeeded', completed_at = now(), score = %s, summary = %s::jsonb WHERE id = %s RETURNING 1""",
              [score, json.dumps({"crawler_access": access, "llms_txt": llms.status_code == 200, "pages_analyzed": len(pages),
                                  "pages_with_schema": with_schema, "pages_with_faq": with_faq,
                                  "note": "robots.txt rules do not prove indexing or citation"}), aid])
    record_audit("geo.audit_completed", "geo", entity_type="geo_audits", entity_id=aid, after={"score": score})
    return str(aid)
