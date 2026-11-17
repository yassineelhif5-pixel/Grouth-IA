"""Opportunity Hunter & Social Opportunity Hunter.

Hunters derive opportunities from evidence actually stored in Growth IA (SEO audits, keywords, GEO observations,
social signals) or fetched from legal public sources (Hacker News Algolia API, RSS feeds, Reddit official API).
Each opportunity carries its evidence, an explainable score and is never silently deleted (dedup = update)."""
from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime

from django.db import transaction

from apps.audit.services import record_activity, record_audit
from apps.core.context import get_context
from apps.core.db import fetch_all_dict, fetch_one
from apps.core.exceptions import BusinessError
from apps.integrations.gateway import IntegrationError, http

TABLES = {"market": "market_opportunities", "saas": "saas_opportunities", "website": "website_opportunities",
          "keyword": "keyword_opportunities", "customer": "customer_opportunities", "trend": "trend_opportunities",
          "partnership": "partnership_opportunities", "revenue": "revenue_opportunities"}
STATUSES = ["new", "detected", "under_analysis", "qualified", "approved", "in_progress", "won", "rejected", "archived"]


def _score(potential: float, confidence: float, difficulty: float) -> tuple[float, list[tuple[str, float, float]]]:
    factors = [("potential", 0.5, potential), ("confidence", 0.3, confidence), ("ease", 0.2, 100 - difficulty)]
    return round(sum(w * v for _, w, v in factors), 1), factors


def upsert(kind: str, *, product_id: str | None, project_id: str | None, hunter: str, key: str, title: str, description: str,
           recommendation: str, potential: float, confidence: float, difficulty: float, evidence: list[dict], data: dict | None = None) -> tuple[str, bool]:
    tid = get_context().tenant_id
    table = TABLES[kind]
    h = hashlib.sha256(f"{hunter}|{product_id}|{key}".encode()).hexdigest()
    score, factors = _score(potential, confidence, difficulty)
    with transaction.atomic():
        existing = fetch_one(f"SELECT id FROM public.{table} WHERE tenant_id = %s AND dedup_hash = %s AND deleted_at IS NULL", [tid, h])  # noqa: S608
        if existing:
            oid, created = existing[0], False
            fetch_one(f"UPDATE public.{table} SET score = %s, confidence = %s, potential = %s, difficulty = %s, description = %s, data = %s::jsonb WHERE id = %s RETURNING 1",  # noqa: S608
                      [score, confidence, potential, difficulty, description, json.dumps(data or {}), oid])
        else:
            oid = fetch_one(f"""INSERT INTO public.{table} (tenant_id, project_id, product_id, title, description, score, status, data, hunter, confidence,
                                   potential, difficulty, recommendation, dedup_hash) VALUES (%s,%s,%s,%s,%s,%s,'detected',%s::jsonb,%s,%s,%s,%s,%s,%s) RETURNING id""",  # noqa: S608
                            [tid, project_id, product_id, title[:500], description, score, json.dumps(data or {}), hunter, confidence, potential,
                             difficulty, recommendation, h])[0]
            created = True
        sid = fetch_one("INSERT INTO public.opportunity_scores (tenant_id, opportunity_type, opportunity_id, score, model_version) VALUES (%s,%s,%s,%s,'rules-v1') RETURNING id",
                        [tid, kind, oid, score])[0]
        for name, w, v in factors:
            fetch_one("INSERT INTO public.opportunity_score_factors (tenant_id, score_id, factor, weight, value) VALUES (%s,%s,%s,%s,%s) RETURNING id", [tid, sid, name, w, v])
        for ev in evidence[:20]:
            fetch_one("INSERT INTO public.opportunity_evidence (tenant_id, opportunity_type, opportunity_id, url, excerpt) VALUES (%s,%s,%s,%s,%s) RETURNING id",
                      [tid, kind, oid, ev.get("url"), json.dumps(ev, default=str)[:4000]])
    if created:
        record_activity("opportunity.detected", "opportunities", entity_type=table, entity_id=oid, product_id=product_id, description=title[:200])
    return str(oid), created


def hunt(project_id: str) -> dict:
    tid = get_context().tenant_id
    p = fetch_one("SELECT product_id, coalesce(hunters, ARRAY['keyword','website','competitor','content_gap','customer']) FROM public.opportunity_search_projects WHERE id = %s AND tenant_id = %s",
                  [project_id, tid])
    if not p:
        raise BusinessError("project not found", "not_found", status_code=404)
    product_id, hunters = (str(p[0]) if p[0] else None), p[1]
    q = fetch_one("INSERT INTO public.opportunity_search_queries (tenant_id, project_id, query, filters) VALUES (%s,%s,%s,%s::jsonb) RETURNING id",
                  [tid, project_id, "hunt:" + ",".join(hunters), json.dumps({"hunters": hunters})])[0]
    created = 0
    if "keyword" in hunters:
        for k in fetch_all_dict("""SELECT k.id, k.keyword, k.search_volume, k.difficulty, (SELECT r.position FROM public.keyword_rankings r WHERE r.keyword_id = k.id ORDER BY r.checked_on DESC LIMIT 1) AS pos
                                    FROM public.seo_keywords k JOIN public.seo_projects sp ON sp.id = k.project_id
                                   WHERE k.tenant_id = %s AND (%s::uuid IS NULL OR sp.product_id = %s::uuid) AND k.deleted_at IS NULL""", [tid, product_id, product_id]):
            pos, vol, diff = k["pos"], k["search_volume"], float(k["difficulty"] or 50)
            if pos and 4 <= pos <= 20 or (vol and vol >= 100 and diff <= 40):
                _, c = upsert("keyword", product_id=product_id, project_id=project_id, hunter="keyword", key=k["keyword"],
                              title=f"Mot-clé à potentiel : {k['keyword']}", description=f"Position actuelle {pos or 'non classé'}, volume {vol or 'inconnu'}, difficulté {k['difficulty'] or 'inconnue'}",
                              recommendation="Créer ou optimiser un contenu ciblant ce mot-clé.", potential=min(100, (vol or 50) / 10 + (30 if pos and pos <= 10 else 10)),
                              confidence=80 if vol else 50, difficulty=diff, evidence=[{"type": "seo_keyword", "id": str(k["id"]), "position": pos, "volume": vol}])
                created += c
    if "website" in hunters:
        last = fetch_one("""SELECT a.id FROM public.seo_audits a JOIN public.seo_projects sp ON sp.id = a.project_id WHERE a.tenant_id = %s
                            AND (%s::uuid IS NULL OR sp.product_id = %s::uuid) AND a.status = 'succeeded' ORDER BY a.completed_at DESC LIMIT 1""", [tid, product_id, product_id])
        if last:
            for i in fetch_all_dict("""SELECT issue_code, severity, count(*) AS n, min(page_url) AS sample FROM public.seo_issues WHERE audit_id = %s
                                        AND severity IN ('critical','high') GROUP BY 1,2""", [last[0]]):
                _, c = upsert("website", product_id=product_id, project_id=project_id, hunter="website", key=i["issue_code"],
                              title=f"Corriger {i['issue_code']} ({i['n']} pages)", description=f"Problème {i['severity']} détecté par l'audit SEO",
                              recommendation="Traiter la recommandation SEO associée.", potential=70 if i["severity"] == "critical" else 55, confidence=95,
                              difficulty=30, evidence=[{"type": "seo_audit", "audit_id": str(last[0]), "sample": i["sample"], "count": i["n"]}])
                created += c
    if "competitor" in hunters or "content_gap" in hunters:
        for g in fetch_all_dict("""SELECT q.id, q.query, count(DISTINCT r.id) AS runs,
                                          array_agg(DISTINCT m.mention_text) FILTER (WHERE m.mention_text IS NOT NULL) AS mentioned
                                     FROM public.ai_search_queries q JOIN public.ai_search_runs r ON r.query_id = q.id AND r.status = 'succeeded'
                                     LEFT JOIN public.ai_search_responses s ON s.run_id = r.id LEFT JOIN public.ai_search_mentions m ON m.response_id = s.id
                                    WHERE q.tenant_id = %s AND (%s::uuid IS NULL OR q.product_id = %s::uuid) GROUP BY q.id""", [tid, product_id, product_id]):
            brand = fetch_one("SELECT name FROM public.products WHERE id = %s", [product_id])[0] if product_id else None
            mentioned = g["mentioned"] or []
            if brand and brand not in mentioned:
                _, c = upsert("market", product_id=product_id, project_id=project_id, hunter="content_gap", key=str(g["id"]),
                              title=f"Absent des réponses IA : « {g['query'][:120]} »", description=f"{g['runs']} réponses observées, marques citées : {', '.join(mentioned) or 'aucune'}",
                              recommendation="Produire un contenu de référence répondant précisément à cette question (GEO).", potential=65,
                              confidence=min(95, 40 + 10 * g["runs"]), difficulty=45, evidence=[{"type": "geo_query", "query_id": str(g["id"]), "competitors_cited": mentioned}])
                created += c
    if "customer" in hunters:
        for s in fetch_all_dict("""SELECT id, url, title, intent, score, source FROM public.social_signals WHERE tenant_id = %s AND status = 'qualified'
                                    AND deleted_at IS NULL ORDER BY created_at DESC LIMIT 100""", [tid]):
            _, c = upsert("customer", product_id=product_id, project_id=project_id, hunter="customer", key=str(s["id"]),
                          title=f"Besoin exprimé publiquement : {(s['title'] or '')[:150]}", description=f"Intention {s['intent']} ({s['source']})",
                          recommendation="Répondre publiquement avec une contribution utile ; pas de prospection sans base légale.",
                          potential=float(s["score"] or 50), confidence=70, difficulty=30, evidence=[{"type": "social_signal", "id": str(s["id"]), "url": s["url"]}])
            created += c
    record_audit("opportunities.hunt", "opportunities", entity_type="opportunity_search_projects", entity_id=project_id, after={"hunters": hunters, "new": created})
    if created:
        from apps.notifications.service import notify
        notify("opportunity.new", {"title": f"{created} nouvelle(s) opportunité(s)"}, permission="opportunities.read")
    return {"query_id": str(q), "new_opportunities": created}


def change_status(kind: str, opp_id: str, status: str, reason: str) -> None:
    if status not in STATUSES:
        raise BusinessError("invalid status", "invalid")
    table = TABLES[kind]
    tid = get_context().tenant_id
    from apps.core.services import change_reason
    with transaction.atomic(), change_reason(reason):
        prev = fetch_one(f"SELECT status FROM public.{table} WHERE id = %s AND tenant_id = %s FOR UPDATE", [opp_id, tid])  # noqa: S608
        if not prev:
            raise BusinessError("opportunity not found", "not_found", status_code=404)
        fetch_one(f"UPDATE public.{table} SET status = %s WHERE id = %s RETURNING 1", [status, opp_id])  # noqa: S608
        fetch_one("INSERT INTO public.opportunity_actions (tenant_id, opportunity_type, opportunity_id, action, assigned_to, status) VALUES (%s,%s,%s,%s,%s,'done') RETURNING id",
                  [tid, kind, opp_id, f"status:{prev[0]}->{status}: {reason}"[:500], get_context().user_id])
        if status in ("won", "rejected"):
            fetch_one("INSERT INTO public.opportunity_outcomes (tenant_id, opportunity_type, opportunity_id, outcome, note) VALUES (%s,%s,%s,%s,%s) RETURNING id",
                      [tid, kind, opp_id, "won" if status == "won" else "abandoned", reason])
        record_audit("opportunity.status_changed", "opportunities", entity_type=table, entity_id=opp_id, before={"status": prev[0]}, after={"status": status},
                     description=reason)


# ───────────── Social Opportunity Hunter ─────────────
INTENT_PATTERNS = [
    ("recommendation_request", r"\b(recommend|recommandez|any suggestions?|des conseils|which (tool|software)|quel (outil|logiciel))\b"),
    ("software_request", r"\b(looking for|je cherche|we need|nous cherchons|searching for) (a |an |un |une )?(tool|software|platform|saas|solution|outil|logiciel)\b"),
    ("solution_search", r"\b(alternative to|alternatives? à|replace|remplacer)\b"),
    ("problem", r"\b(struggling|frustrated|problème|galère|pain point|doesn'?t work)\b"),
    ("commercial_intent", r"\b(pricing|budget|devis|quote|buy|acheter|subscription)\b"),
]


def classify_intent(text: str) -> tuple[str, float]:
    low = text.lower()
    hits = [(name, len(re.findall(p, low))) for name, p in INTENT_PATTERNS]
    hits = [h for h in hits if h[1]]
    if not hits:
        return "discussion", 20.0
    best = max(hits, key=lambda h: h[1])
    return best[0], min(100.0, 40 + 15 * sum(h[1] for h in hits))


def _fetch_source(source: str, keywords: list[str]) -> list[dict]:
    items: list[dict] = []
    if source == "hackernews":
        for kw in keywords[:10]:
            try:
                d = http("GET", "https://hn.algolia.com/api/v1/search_by_date", provider="hackernews", operation="search",
                         params={"query": kw, "tags": "(story,comment)", "hitsPerPage": 30}).json()
            except IntegrationError:
                continue
            for h in d.get("hits", []):
                items.append({"source": "hackernews", "external_id": h["objectID"], "url": f"https://news.ycombinator.com/item?id={h['objectID']}",
                              "author": h.get("author"), "title": h.get("title") or h.get("story_title"),
                              "content": re.sub("<[^>]+>", " ", h.get("comment_text") or h.get("story_text") or h.get("title") or ""),
                              "published_at": h.get("created_at")})
    elif source.startswith("rss:"):
        try:
            r = http("GET", source[4:], provider="rss", operation="fetch")
            root = ET.fromstring(r.content)
        except (IntegrationError, ET.ParseError):
            return items
        for it in root.iter():
            if it.tag.endswith("item") or it.tag.endswith("entry"):
                g = {c.tag.split("}")[-1]: (c.text or c.attrib.get("href") or "") for c in it}
                link = g.get("link") or g.get("id")
                items.append({"source": "rss", "external_id": link, "url": link, "author": g.get("author"), "title": g.get("title"),
                              "content": re.sub("<[^>]+>", " ", g.get("description") or g.get("summary") or g.get("content") or ""),
                              "published_at": None})
    return items


def listen(config_id: str) -> dict:
    tid = get_context().tenant_id
    c = fetch_one("""SELECT coalesce(keywords,'{}'), coalesce(negative_keywords,'{}'), coalesce(sources, ARRAY['hackernews']), coalesce(languages,'{}')
                       FROM public.social_listening_configs WHERE id = %s AND tenant_id = %s AND deleted_at IS NULL""", [config_id, tid])
    if not c:
        raise BusinessError("config not found", "not_found", status_code=404)
    kws, neg, sources, _langs = c
    if not kws:
        raise BusinessError("At least one keyword is required", "invalid")
    new = dup = 0
    for src in sources:
        for it in _fetch_source(src, kws):
            text = f"{it.get('title') or ''} {it.get('content') or ''}"
            low = text.lower()
            matched = [k for k in kws if k.lower() in low]
            if not matched or any(n.lower() in low for n in neg):
                continue
            intent, score = classify_intent(text)
            h = hashlib.sha256(f"{it['source']}|{it['external_id']}".encode()).hexdigest()
            row = fetch_one("""INSERT INTO public.social_signals (tenant_id, config_id, source, external_id, url, author_handle, title, content, published_at,
                                 intent, score, confidence, dedup_hash, evidence)
                               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                               ON CONFLICT (tenant_id, dedup_hash) WHERE deleted_at IS NULL DO NOTHING RETURNING id""",
                            [tid, config_id, it["source"], str(it["external_id"])[:500], it.get("url"), it.get("author"), (it.get("title") or "")[:500],
                             (it.get("content") or "")[:5000], it.get("published_at"), intent, score, 60,
                             h, json.dumps({"matched_keywords": matched, "method": "keyword+rules-v1",
                                            "consent_note": "Public conversation ≠ consent to receive prospecting"})])
            if row:
                new += 1
            else:
                dup += 1
    fetch_one("UPDATE public.social_listening_configs SET last_run_at = %s WHERE id = %s RETURNING 1", [datetime.now(UTC), config_id])
    record_activity("social_hunter.run", "opportunities", entity_type="social_listening_configs", entity_id=config_id,
                    description=f"{new} nouveaux signaux, {dup} doublons ignorés")
    return {"new": new, "duplicates": dup}
