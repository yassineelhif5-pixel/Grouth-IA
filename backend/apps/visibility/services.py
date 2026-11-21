"""Visibility programmes — audit pipeline, recommendations, validation & scheduling, assistant, KPIs.

Principles
- Observed facts (crawl, HTTP checks, GEO runs) and AI output are stored separately; AI output is labelled.
- Nothing is invented: without an AI route, summaries are rule-based; without Search Console/GA4, KPIs say "not connected".
- A validated action is applied automatically when a connector allows it (CMS, social); otherwise the generated asset is
  delivered ready to deploy with instructions. Outbound actions still go through the tenant growth mode.
"""
from __future__ import annotations

import json
import logging
import re
import time
from urllib.parse import urlparse

import requests
from django.conf import settings
from django.db import transaction

from apps.audit.services import record_activity, record_audit
from apps.core.context import get_context
from apps.core.db import fetch_all_dict, fetch_one
from apps.core.exceptions import BusinessError

from . import analyzer

logger = logging.getLogger("growth.visibility")

CHANNELS = [  # publication targets suggested to reach the top of the domain (only official APIs / manual posting)
    {"code": "blog", "name": "Blog du site (WordPress, Ghost, CMS)", "why": "Contenus indexables qui captent la longue traîne et sont cités par les moteurs IA",
     "connector": ["wordpress", "ghost", "generic_rest"], "default_frequency": ("weekly", 2)},
    {"code": "linkedin", "name": "LinkedIn (page entreprise)", "why": "Audience B2B, signaux de marque, trafic qualifié",
     "connector": ["linkedin"], "default_frequency": ("weekly", 3)},
    {"code": "medium", "name": "Medium / Substack", "why": "Republication canonique vers le site, autorité et backlinks",
     "connector": [], "default_frequency": ("monthly", 2)},
    {"code": "devto", "name": "dev.to / Hashnode", "why": "Audience technique, liens vers la documentation", "connector": [],
     "default_frequency": ("monthly", 2)},
    {"code": "product_hunt", "name": "Product Hunt", "why": "Lancement, avis et backlinks d'autorité", "connector": [],
     "default_frequency": ("once", 1)},
    {"code": "review_sites", "name": "G2 / Capterra / GetApp", "why": "Avis clients très cités par les moteurs IA dans les comparatifs",
     "connector": [], "default_frequency": ("monthly", 1)},
    {"code": "reddit", "name": "Reddit / forums spécialisés", "why": "Réponses utiles dans les communautés (sans spam), sources souvent citées par l'IA",
     "connector": [], "default_frequency": ("weekly", 1)},
    {"code": "youtube", "name": "YouTube (démos, tutoriels)", "why": "Deuxième moteur de recherche, vidéos intégrées aux réponses IA",
     "connector": [], "default_frequency": ("monthly", 2)},
    {"code": "google_business", "name": "Google Business Profile", "why": "Présence locale et fiche de marque", "connector": [],
     "default_frequency": ("monthly", 2)},
    {"code": "x", "name": "X (Twitter)", "why": "Annonces produit et veille", "connector": [], "default_frequency": ("weekly", 3)},
]

FUNDAMENTAL_QUESTIONS = [
    ("offer", "Que fait votre SaaS, en une phrase, et quel problème résout-il ?"),
    ("audience", "Qui sont vos clients cibles (métier, taille d'entreprise, secteur) ?"),
    ("countries", "Dans quels pays et quelles langues voulez-vous être visible ?"),
    ("competitors", "Quels sont vos 3 à 5 principaux concurrents (noms ou sites) ?"),
    ("differentiators", "Qu'est-ce qui vous différencie de ces concurrents ?"),
    ("goals", "Quel objectif prioritaire : trafic, inscriptions, démos, notoriété, citations par les IA ?"),
    ("keywords", "Quels mots ou expressions vos clients tapent-ils pour vous trouver ?"),
    ("assets", "Avez-vous un blog, une documentation, des études de cas, des chiffres clés publiables ?"),
    ("channels", "Sur quels canaux publiez-vous déjà (LinkedIn, blog, YouTube…) et à quel rythme ?"),
    ("autonomy", "Quel niveau d'autonomie souhaitez-vous : tout valider, valider les publications seulement, ou automatique ?"),
]

FREQ_TO_SCHEDULER = {"daily": ("daily", "09:00"), "weekly": ("weekly", "0 09:00"), "monthly": ("monthly", "1 09:00"), "once": ("daily", "09:00")}


# ───────────────────────────── profiles ─────────────────────────────
def create_profile(data: dict) -> str:
    tid = get_context().tenant_id
    urls = [u.strip() for u in data.get("site_urls") or [] if u and u.strip()]
    if not urls:
        raise BusinessError("Indiquez au moins un lien vers votre site.", "site_url_required")
    urls = [u if "://" in u else f"https://{u}" for u in urls]
    product_id = data.get("product_id") or _ensure_product(data.get("name") or urlparse(urls[0]).netloc, urls[0])
    ans = data.get("answers") or {}
    competitors = [_norm_comp(c) for c in data.get("competitors") or [] if c]
    if not competitors and ans.get("competitors"):  # answers given to the assistant pre-fill the profile
        competitors = [_norm_comp(c.strip()) for c in re.split(r"[,;\n]", str(ans["competitors"])) if c.strip()][:5]
    data = {**data, "audience": data.get("audience") or ans.get("audience"), "offer": data.get("offer") or ans.get("offer")}
    pid = fetch_one("""INSERT INTO public.visibility_profiles (tenant_id, product_id, name, site_urls, sector, audience, offer,
                         languages, countries, competitors, goals, answers)
                       VALUES (%s,%s,%s,%s::jsonb,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb) RETURNING id""",
                    [tid, product_id, data.get("name") or urlparse(urls[0]).netloc, json.dumps(urls), data.get("sector"),
                     data.get("audience"), data.get("offer"), json.dumps(data.get("languages") or ["fr"]),
                     json.dumps(data.get("countries") or ["FR"]), json.dumps(competitors), json.dumps(data.get("goals") or []),
                     json.dumps(data.get("answers") or {})])[0]
    record_activity("visibility.profile_created", "visibility", entity_type="visibility_profiles", entity_id=pid,
                    description=f"Profil de visibilité créé pour {urls[0]}")
    return str(pid)


def _norm_comp(c) -> dict:
    if isinstance(c, dict):
        url = (c.get("url") or "").strip()
        return {"name": c.get("name") or urlparse(url).netloc or url, "url": url if not url or "://" in url else f"https://{url}",
                "source": c.get("source") or "user"}
    c = str(c).strip()
    looks_url = "." in c and " " not in c
    return {"name": urlparse(c if "://" in c else f"https://{c}").netloc if looks_url else c,
            "url": (c if "://" in c else f"https://{c}") if looks_url else "", "source": "user"}


def _ensure_product(name: str, url: str) -> str:
    tid = get_context().tenant_id
    row = fetch_one("SELECT id FROM public.products WHERE tenant_id = %s AND deleted_at IS NULL AND (url = %s OR primary_domain = %s) LIMIT 1",
                    [tid, url, urlparse(url).netloc])
    if row:
        return str(row[0])
    from apps.licensing.services import check_quota
    check_quota(tid, "products.max")
    import re
    import secrets
    slug = (re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "saas") + "-" + secrets.token_hex(3)
    return str(fetch_one("""INSERT INTO public.products (tenant_id, name, slug, url, primary_domain, status)
                            VALUES (%s,%s,%s,%s,%s,'active') RETURNING id""", [tid, name[:200], slug, url, urlparse(url).netloc])[0])


# ───────────────────────────── audit pipeline ─────────────────────────────
def launch_audit(profile_id: str, scope: list[str] | None = None, audit_type: str = "site") -> str:
    from apps.licensing.services import check_quota
    tid = get_context().tenant_id
    check_quota(tid, "visibility.audits.monthly")
    if not fetch_one("SELECT 1 FROM public.visibility_profiles WHERE id = %s AND tenant_id = %s AND deleted_at IS NULL", [profile_id, tid]):
        raise BusinessError("Profil introuvable", "not_found", status_code=404)
    aid = str(fetch_one("""INSERT INTO public.visibility_audits (tenant_id, profile_id, audit_type, scope, status, step)
                           VALUES (%s,%s,%s,%s::jsonb,'queued','En file d''attente') RETURNING id""",
                        [tid, profile_id, audit_type, json.dumps(scope or ["seo", "geo"])])[0])
    record_audit("visibility.audit_launched", "visibility", entity_type="visibility_audits", entity_id=aid, after={"scope": scope})
    from .tasks import run_visibility_audit
    transaction.on_commit(lambda: run_visibility_audit.delay_traced(aid))
    return aid


def _progress(aid: str, pct: int, step: str) -> None:
    fetch_one("UPDATE public.visibility_audits SET progress = %s, step = %s, status = 'running', started_at = coalesce(started_at, now()) WHERE id = %s RETURNING 1",
              [pct, step, aid])


def execute_audit(aid: str) -> dict:
    from apps.seo.crawler import Crawler
    row = fetch_one("""SELECT a.profile_id, a.scope, a.audit_type, p.name, p.site_urls, p.competitors, p.languages, p.sector, p.offer, p.product_id
                         FROM public.visibility_audits a JOIN public.visibility_profiles p ON p.id = a.profile_id WHERE a.id = %s""", [aid])
    if not row:
        raise BusinessError("Audit introuvable", "not_found")
    profile_id, scope, audit_type, name, urls, competitors, languages, sector, offer, product_id = row
    ua = settings.CRAWLER_USER_AGENT
    max_pages = min(int(getattr(settings, "CRAWLER_MAX_PAGES", 50)), 30)
    t0 = time.monotonic()
    try:
        site: dict = {"sites": []}
        all_pages, kw_docs = [], []
        for i, url in enumerate(urls[:5]):
            _progress(aid, 5 + i * 5, f"Analyse technique de {urlparse(url).netloc}")
            tech = analyzer.technical_checks(url, ua)
            _progress(aid, 15 + i * 5, f"Exploration des pages de {urlparse(url).netloc}")
            crawl = Crawler(ua, max_pages=max_pages, delay=settings.CRAWLER_DELAY_SECONDS).crawl(url)
            pages = [p.as_dict() for p in crawl.pages]
            all_pages += pages
            kw_docs += analyzer.page_documents(pages, tech.get("home", {}).get("text", ""))
            site["sites"].append({"url": url, "root": tech.get("root"), "checks": tech["checks"], "score": analyzer.score_checks(tech["checks"]),
                                  "pages_crawled": len(pages), "sitemap_urls_count": len(tech.get("sitemap_urls") or []),
                                  "seo_issues": [i.__dict__ for i in crawl.issues][:200], "seo_score": crawl.score,
                                  "home": {k: v for k, v in (tech.get("home") or {}).items() if k != "text"},
                                  "sitemap_urls": (tech.get("sitemap_urls") or [])[:2000],
                                  "page_urls": [p["url"] for p in pages if (p.get("status_code") or 0) < 400]})
        _progress(aid, 40, "Extraction des mots-clés et du domaine")
        site["keywords"] = analyzer.extract_keywords(kw_docs)
        site["domain"] = urlparse(urls[0]).netloc
        site["pages"] = [{k: p.get(k) for k in ("url", "status_code", "title", "meta_description", "word_count", "h1", "schema_types")}
                         for p in all_pages][:100]
        fetch_one("UPDATE public.visibility_audits SET site_findings = %s::jsonb WHERE id = %s RETURNING 1", [json.dumps(site, default=str), aid])

        _progress(aid, 50, "Recherche des concurrents")
        comps = list(competitors or [])
        if len([c for c in comps if c.get("url")]) < 2:
            comps += _ai_suggest_competitors(name, sector, offer, site["keywords"], urls[0], product_id)
        comp_findings: dict = {"competitors": []}
        comp_kw: dict[str, list[dict]] = {}
        for j, c in enumerate([c for c in comps if c.get("url")][:5]):
            _progress(aid, 55 + j * 5, f"Analyse du concurrent {c['name']}")
            try:
                ctech = analyzer.technical_checks(c["url"], ua)
                ccrawl = Crawler(ua, max_pages=8, delay=settings.CRAWLER_DELAY_SECONDS).crawl(c["url"])
                cpages = [p.as_dict() for p in ccrawl.pages]
                kws = analyzer.extract_keywords(analyzer.page_documents(cpages, ctech.get("home", {}).get("text", "")), top=30)
                comp_kw[c["name"]] = kws
                comp_findings["competitors"].append({**c, "score": analyzer.score_checks(ctech["checks"]), "keywords": kws[:20],
                                                     "jsonld_types": (ctech.get("home") or {}).get("jsonld_types", []),
                                                     "has_llms_txt": any(x["code"] == "llms_txt" and x["status"] == "ok" for x in ctech["checks"]),
                                                     "pages_crawled": len(cpages)})
            except Exception as e:  # noqa: BLE001 — one unreachable competitor must not fail the audit
                comp_findings["competitors"].append({**c, "error": type(e).__name__})
        comp_findings["keyword_gap"] = analyzer.keyword_gap(site["keywords"], comp_kw)
        fetch_one("UPDATE public.visibility_audits SET competitor_findings = %s::jsonb WHERE id = %s RETURNING 1",
                  [json.dumps(comp_findings, default=str), aid])

        _progress(aid, 82, "Synthèse et recommandations")
        recs = build_recommendations(site, comp_findings, scope or [])
        summary = _ai_summary(name, site, comp_findings, recs, product_id)
        _progress(aid, 90, "Génération des fichiers techniques")
        assets = build_assets(name, site, languages or ["fr"], offer)
        _store_outputs(aid, profile_id, recs, assets, summary)
        score = round(sum(s["score"] for s in site["sites"]) / max(len(site["sites"]), 1))
        fetch_one("""UPDATE public.visibility_audits SET status = 'succeeded', progress = 100, step = 'Terminé', ai_summary = %s::jsonb,
                     score = %s, finished_at = now() WHERE id = %s RETURNING 1""", [json.dumps(summary, default=str), score, aid])
        record_audit("visibility.audit_completed", "visibility", entity_type="visibility_audits", entity_id=aid,
                     after={"score": score, "recommendations": len(recs), "duration_ms": int((time.monotonic() - t0) * 1000)})
        record_activity("visibility.audit_completed", "visibility", entity_type="visibility_audits", entity_id=aid,
                        description=f"Audit de visibilité terminé (score {score}/100, {len(recs)} recommandations)")
        return {"audit_id": aid, "score": score, "recommendations": len(recs)}
    except Exception as e:
        fetch_one("UPDATE public.visibility_audits SET status = 'failed', error = %s, step = 'Échec', finished_at = now() WHERE id = %s RETURNING 1",
                  [str(e)[:500], aid])
        raise


def _ai_suggest_competitors(name, sector, offer, keywords, url, product_id) -> list[dict]:
    from apps.ai_providers.gateway import AINotConfigured, complete
    prompt = (f"SaaS : {name} ({url}). Secteur : {sector or 'inconnu'}. Offre : {offer or 'inconnue'}. "
              f"Mots-clés observés sur le site : {', '.join(k['keyword'] for k in keywords[:15])}. "
              "Donne 5 concurrents SaaS directs réels avec leur site officiel. Réponds uniquement en JSON : "
              '[{"name": "...", "url": "https://..."}]')
    try:
        res = complete("visibility_competitors", [{"role": "user", "content": prompt}], max_tokens=500, product_id=product_id,
                       agent_code="visibility")
        items = res.json()
        return [{"name": str(i.get("name"))[:100], "url": str(i.get("url"))[:300], "source": "ai_suggested"}
                for i in items if isinstance(i, dict) and str(i.get("url", "")).startswith("http")][:5]
    except (AINotConfigured, ValueError, TypeError, json.JSONDecodeError):
        return []


def build_recommendations(site: dict, comp: dict, scope: list[str]) -> list[dict]:
    recs: list[dict] = []

    def add(category, code, title, detail, priority, apply_mode, impact, effort, evidence=None, channel=None):
        recs.append({"category": category, "code": code, "title": title, "detail": detail, "priority": priority,
                     "apply_mode": apply_mode, "impact": impact, "effort": effort, "evidence": evidence or {}, "channel": channel})

    asset_for = {"robots_txt": "robots_txt", "sitemap_xml": "sitemap_xml", "sitemap_images": "sitemap_images_xml",
                 "json_ld": "json_ld", "open_graph": "open_graph", "hreflang": "hreflang", "canonical": "canonical",
                 "page_404": "page_404", "redirect_301": "redirects", "llms_txt": "llms_txt", "ai_crawlers": "robots_txt"}
    for s in site.get("sites", []):
        for c in s["checks"]:
            if c["status"] in ("ok", "info") and c["code"] not in ("llms_txt", "hreflang", "sitemap_images"):
                continue
            if c["status"] == "ok":
                continue
            prio = "critical" if c["status"] == "error" and c["code"] in ("https", "reachable", "robots_txt", "sitemap_xml") else \
                "high" if c["status"] == "error" else "medium" if c["status"] == "warning" else "low"
            mode = "generated_file" if c["code"] in asset_for else "manual"
            add("technical", c["code"], f"{c['label']} — {s['url']}", c["detail"], prio, mode,
                "Indexation et compréhension du site par Google, Bing et les moteurs IA", "faible" if mode == "generated_file" else "moyen",
                {"check": c, "asset": asset_for.get(c["code"])})
        for issue in s.get("seo_issues", [])[:15]:
            if issue.get("severity") in ("critical", "high"):
                add("technical", f"seo_{issue['code']}", issue["description"][:200], f"Page : {issue.get('page_url') or '—'}",
                    "high", "manual", "Erreur SEO bloquante relevée par le crawl", "moyen", issue)
    gap = comp.get("keyword_gap") or []
    for g in gap[:8]:
        add("keywords", "keyword_gap", f"Créer un contenu ciblant « {g['keyword']} »",
            f"Utilisé par {', '.join(g['competitors'][:3])}, absent de votre site.", "high" if len(g["competitors"]) > 1 else "medium",
            "ai_content", "Capter des requêtes déjà travaillées par vos concurrents", "moyen", g, channel="blog")
    top_kw = [k["keyword"] for k in site.get("keywords", [])[:5]]
    if top_kw:
        add("content", "pillar_article", f"Article pilier : guide complet « {top_kw[0]} »",
            "Article long (2 000+ mots) avec étude, statistiques sourcées, comparatif et FAQ, maillé vers vos pages clés.",
            "high", "ai_content", "Autorité thématique et citations IA", "moyen", {"keywords": top_kw}, channel="blog")
        add("content", "comparison_article", f"Comparatif : {site.get('domain')} vs alternatives",
            "Page comparative honnête (tableau de fonctionnalités, prix publics, cas d'usage) : format très repris par les moteurs IA.",
            "high", "ai_content", "Requêtes « alternative à… » et « meilleur logiciel… »", "moyen", {"keywords": top_kw}, channel="blog")
        add("content", "faq_page", "Page FAQ structurée (FAQPage JSON-LD)",
            "Répondre aux 10 questions les plus posées par vos clients avec un balisage FAQPage.", "medium", "ai_content",
            "Extraits enrichis et réponses IA", "faible", {"keywords": top_kw}, channel="blog")
    if "geo" in scope or True:
        comps_llms = [c["name"] for c in comp.get("competitors", []) if c.get("has_llms_txt")]
        add("geo", "ai_questions", "Suivre votre présence dans ChatGPT, Claude, Gemini et Perplexity",
            "Bibliothèque de questions de votre secteur testée régulièrement (mentions et citations réellement observées).",
            "high", "manual", "Mesurer et améliorer l'AI Mention Rate", "faible", {"competitors_with_llms_txt": comps_llms})
        add("geo", "citable_stats", "Publier une page « chiffres clés » citable",
            "Statistiques propres datées et sourcées (études, usage) : les moteurs IA citent les sources de données originales.",
            "medium", "ai_content", "AI Citation Rate", "moyen", {}, channel="blog")
    for ch in CHANNELS:
        if ch["code"] in ("blog",):
            continue
        add("social", f"channel_{ch['code']}", f"Publier sur {ch['name']}", ch["why"], "medium" if ch["code"] in ("linkedin", "review_sites") else "low",
            "auto_connector" if ch["connector"] else "manual", "Visibilité de marque et backlinks", "faible", {"channel": ch}, channel=ch["code"])
    if "prospect" in scope:
        add("prospect", "icp_from_keywords", "Créer une campagne Smart Prospect à partir de vos mots-clés",
            "Cible définie à partir des thématiques observées sur votre site, avec consentement et désinscription.", "medium",
            "manual", "Prospects qualifiés", "moyen", {"keywords": top_kw})
        add("prospect", "social_signals", "Veille des conversations (Social Opportunity Hunter)",
            "Surveiller les discussions publiques sur vos thématiques pour y répondre utilement (une discussion publique n'est pas un consentement).",
            "low", "manual", "Opportunités entrantes", "faible", {"keywords": top_kw})
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    return sorted(recs, key=lambda r: order[r["priority"]])


def _ai_summary(name, site, comp, recs, product_id) -> dict:
    """AI synthesis when configured (labelled), rule-based otherwise."""
    from apps.ai_providers.gateway import AINotConfigured, complete, wrap_untrusted
    facts = {"site": [{"url": s["url"], "score": s["score"], "checks": [(c["code"], c["status"]) for c in s["checks"]]} for s in site["sites"]],
             "keywords": [k["keyword"] for k in site.get("keywords", [])[:20]],
             "competitors": [{"name": c["name"], "score": c.get("score"), "keywords": [k["keyword"] for k in c.get("keywords", [])[:10]]}
                             for c in comp.get("competitors", [])],
             "keyword_gap": [g["keyword"] for g in comp.get("keyword_gap", [])[:15]],
             "top_recommendations": [r["title"] for r in recs[:12]]}
    try:
        res = complete("visibility_summary", [{"role": "user", "content": (
            f"Tu es expert SEO et GEO (visibilité dans les moteurs IA). Voici les constats observés pour le SaaS {name} :\n"
            + wrap_untrusted("audit", json.dumps(facts, ensure_ascii=False)) +
            "\nRédige en français un plan pour atteindre la 1re position du domaine. Réponds uniquement en JSON avec : "
            '{"summary": "...", "what_to_do": ["..."], "what_to_publish": [{"title": "...", "format": "article|faq|comparatif|etude|post", '
            '"channel": "blog|linkedin|...", "keyword": "..."}], "quick_wins": ["..."], "kpis": ["..."]}')}],
            max_tokens=1800, untrusted=True, product_id=product_id, agent_code="visibility")
        data = res.json()
        data["source"] = "ai"
        data["model"] = res.model
        return data
    except (AINotConfigured, ValueError, TypeError, json.JSONDecodeError):
        crit = [r["title"] for r in recs if r["priority"] in ("critical", "high")][:8]
        return {"source": "rules", "summary": (f"{len(recs)} actions identifiées dont {len(crit)} prioritaires. Score technique moyen "
                                               f"{round(sum(s['score'] for s in site['sites']) / max(len(site['sites']), 1))}/100."),
                "what_to_do": crit,
                "what_to_publish": [{"title": r["title"], "format": "article", "channel": r.get("channel") or "blog",
                                     "keyword": (r.get("evidence") or {}).get("keyword")} for r in recs if r["apply_mode"] == "ai_content"][:6],
                "quick_wins": [r["title"] for r in recs if r["apply_mode"] == "generated_file"][:6],
                "kpis": ["Pages indexées", "Impressions Google", "Clics organiques", "Position moyenne", "AI Mention Rate", "AI Citation Rate"],
                "note": "Synthèse fondée sur des règles : configurez un fournisseur IA dans la console PILOTE pour une synthèse rédigée par l'IA."}


def build_assets(name: str, site: dict, languages: list[str], offer: str | None) -> list[dict]:
    if not site.get("sites"):
        return []
    s0 = site["sites"][0]
    root = s0.get("root") or s0["url"].rstrip("/")
    host = urlparse(root).netloc
    home = s0.get("home") or {}
    desc = home.get("meta_description") or offer or f"{name} — logiciel SaaS"
    urls = sorted(set((s0.get("sitemap_urls") or []) + (s0.get("page_urls") or []))) or [root + "/"]
    key_pages = [(p["url"], p.get("title")) for p in site.get("pages", []) if (p.get("status_code") or 0) < 400][:30]
    faq = [(f"Qu'est-ce que {name} ?", desc), (f"À qui s'adresse {name} ?", "Aux équipes qui veulent " + (offer or "gagner du temps") + ".")]
    return [
        {"asset_type": "robots_txt", "filename": "robots.txt", "content": analyzer.gen_robots(root, None), "content_type": "text/plain"},
        {"asset_type": "sitemap_xml", "filename": "sitemap.xml", "content": analyzer.gen_sitemap(urls), "content_type": "application/xml"},
        {"asset_type": "sitemap_images_xml", "filename": "sitemap-images.xml", "content": analyzer.gen_sitemap_images([]), "content_type": "application/xml"},
        {"asset_type": "json_ld", "filename": "json-ld.html", "content": analyzer.gen_jsonld(name, root, desc, None, [], faq), "content_type": "text/html"},
        {"asset_type": "open_graph", "filename": "open-graph.html",
         "content": analyzer.gen_open_graph(name, root, home.get("title") or name, desc, (home.get("open_graph") or {}).get("og:image")),
         "content_type": "text/html"},
        {"asset_type": "hreflang", "filename": "hreflang.html", "content": analyzer.gen_hreflang(root, languages), "content_type": "text/html"},
        {"asset_type": "canonical", "filename": "canonical.html", "content": analyzer.gen_canonical(root), "content_type": "text/html"},
        {"asset_type": "page_404", "filename": "404.html", "content": analyzer.gen_404(name, root), "content_type": "text/html"},
        {"asset_type": "redirects", "filename": "redirects-301.conf", "content": analyzer.gen_redirects(host), "content_type": "text/plain"},
        {"asset_type": "llms_txt", "filename": "llms.txt", "content": analyzer.gen_llms_txt(name, root, desc, key_pages), "content_type": "text/plain"},
    ]


def _store_outputs(aid: str, profile_id: str, recs: list[dict], assets: list[dict], summary: dict) -> None:
    tid = get_context().tenant_id
    asset_ids = {}
    for a in assets:
        asset_ids[a["asset_type"]] = str(fetch_one("""INSERT INTO public.visibility_generated_assets (tenant_id, audit_id, asset_type, filename, content, content_type)
                                                      VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""",
                                                   [tid, aid, a["asset_type"], a["filename"], a["content"], a["content_type"]])[0])
    for r in recs:
        ev = dict(r["evidence"] or {})
        if ev.get("asset") in asset_ids:
            ev["asset_id"] = asset_ids[ev["asset"]]
        freq = None
        if r["apply_mode"] in ("ai_content", "auto_connector"):
            ch = next((c for c in CHANNELS if c["code"] == (r.get("channel") or "blog")), None)
            freq = ch["default_frequency"] if ch else ("weekly", 1)
        fetch_one("""INSERT INTO public.visibility_recommendations (tenant_id, audit_id, profile_id, category, code, title, detail, priority,
                       impact, effort, evidence, apply_mode, channel, frequency, times_per_period)
                     VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s) RETURNING id""",
                  [tid, aid, profile_id, r["category"], r["code"], r["title"][:300], r["detail"], r["priority"], r["impact"], r["effort"],
                   json.dumps(ev, default=str), r["apply_mode"], r.get("channel"), freq[0] if freq else None, freq[1] if freq else None])
    _build_roadmap(aid, recs, summary)


def _build_roadmap(aid: str, recs: list[dict], summary: dict) -> None:
    tid = get_context().tenant_id
    area = {"technical": "technical", "keywords": "seo", "content": "content", "geo": "ai_search", "social": "publishing",
            "prospect": "measurement", "backlinks": "seo"}
    for r in recs[:40]:
        phase = "now" if r["priority"] in ("critical", "high") and r["category"] == "technical" else \
            "next" if r["priority"] in ("critical", "high") else "later"
        fetch_one("""INSERT INTO public.tenant_roadmap_items (tenant_id, audit_id, phase, area, title, detail, priority, kpi)
                     VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                  [tid, aid, phase, area.get(r["category"], "seo"), r["title"][:300], r["detail"], r["priority"], r["impact"]])
    for k in ("Mesurer : connecter Google Search Console et GA4 (pages indexées, impressions, clics, position, trafic organique)",
              "Mesurer : suivre l'AI Mention Rate et l'AI Citation Rate chaque semaine"):
        fetch_one("""INSERT INTO public.tenant_roadmap_items (tenant_id, audit_id, phase, area, title, priority, kpi)
                     VALUES (%s,%s,'now','measurement',%s,'high','KPI') RETURNING id""", [tid, aid, k])


# ───────────────────────────── validation & application ─────────────────────────────
def accept_recommendation(rec_id: str, frequency: str | None, times: int | None, scheduler_kind: str = "standard",
                          autonomy: str = "approval", run_now: bool = False) -> dict:
    """User validated the action: apply it now when possible, schedule it when recurring."""
    tid = get_context().tenant_id
    r = fetch_all_dict("""SELECT r.*, p.product_id, p.name AS profile_name FROM public.visibility_recommendations r
                            JOIN public.visibility_profiles p ON p.id = r.profile_id
                           WHERE r.id = %s AND r.tenant_id = %s AND r.deleted_at IS NULL""", [rec_id, tid])
    if not r:
        raise BusinessError("Recommandation introuvable", "not_found", status_code=404)
    r = r[0]
    frequency = frequency or r["frequency"] or "once"
    times = max(1, min(int(times or r["times_per_period"] or 1), 30))
    result: dict = {"recommendation_id": rec_id, "apply_mode": r["apply_mode"]}
    if r["apply_mode"] == "generated_file":
        aid = (r["evidence"] or {}).get("asset_id")
        result |= {"status": "accepted", "asset_id": aid,
                   "how_to_apply": "Fichier généré prêt à déployer : téléchargez-le et placez-le à la racine du site (ou dans le <head> pour "
                                   "les balises). Avec un connecteur CMS, Growth IA le publie directement."}
        new_status = "accepted"
        if r["channel"] in ("wordpress", "ghost") or _cms_connected():
            result["cms_available"] = True
    elif r["apply_mode"] in ("ai_content", "auto_connector"):
        sched = create_programme_scheduler(r, frequency, times, scheduler_kind, autonomy)
        result |= {"status": "scheduled", "scheduler_id": sched}
        if run_now:
            from apps.scheduler.engine import enqueue_run
            result["run_id"] = enqueue_run(sched, "manual")
        new_status = "scheduled"
    else:
        result |= {"status": "accepted", "how_to_apply": "Action manuelle ajoutée à la roadmap."}
        new_status = "accepted"
    fetch_one("""UPDATE public.visibility_recommendations SET status = %s, frequency = %s, times_per_period = %s, applied_result = %s::jsonb,
                 applied_at = CASE WHEN %s = 'applied' THEN now() ELSE applied_at END WHERE id = %s RETURNING 1""",
              [new_status, frequency, times, json.dumps(result, default=str), new_status, rec_id])
    fetch_one("UPDATE public.tenant_roadmap_items SET status = 'in_progress' WHERE tenant_id = %s AND title = %s AND status = 'todo' RETURNING 1",
              [tid, r["title"]])
    record_audit("visibility.recommendation_accepted", "visibility", entity_type="visibility_recommendations", entity_id=rec_id,
                 after={"frequency": frequency, "times": times, "kind": scheduler_kind, "autonomy": autonomy, "status": new_status})
    return result


def reject_recommendation(rec_id: str, reason: str) -> None:
    fetch_one("UPDATE public.visibility_recommendations SET status = 'rejected', applied_result = %s::jsonb WHERE id = %s AND tenant_id = %s RETURNING 1",
              [json.dumps({"reason": reason}), rec_id, get_context().tenant_id])
    record_audit("visibility.recommendation_rejected", "visibility", entity_type="visibility_recommendations", entity_id=rec_id, description=reason)


def _cms_connected() -> bool:
    return bool(fetch_one("""SELECT EXISTS (SELECT 1 FROM public.tenant_connector_accounts a JOIN public.connector_providers p ON p.id = a.provider_id
                              WHERE a.tenant_id = %s AND a.deleted_at IS NULL AND a.status IN ('connected','tested')
                                AND p.code IN ('wordpress','ghost','generic_rest'))""", [get_context().tenant_id])[0])


def _content_project(product_id: str, name: str) -> str:
    tid = get_context().tenant_id
    row = fetch_one("SELECT id FROM public.content_projects WHERE tenant_id = %s AND product_id = %s AND name = %s AND deleted_at IS NULL",
                    [tid, product_id, f"Visibilité — {name}"[:200]])
    if row:
        return str(row[0])
    return str(fetch_one("INSERT INTO public.content_projects (tenant_id, product_id, name) VALUES (%s,%s,%s) RETURNING id",
                         [tid, product_id, f"Visibilité — {name}"[:200]])[0])


def create_programme_scheduler(r: dict, frequency: str, times: int, kind: str, autonomy: str) -> str:
    """One scheduler per validated recurring action (quota scheduler.configurations, declared by the PILOTE)."""
    from apps.licensing.services import check_quota
    from apps.scheduler.engine import next_run
    tid = get_context().tenant_id
    check_quota(tid, "scheduler.configurations")
    ftype, fval = FREQ_TO_SCHEDULER.get(frequency, ("weekly", "0 09:00"))
    if frequency == "once":  # single execution: event-type scheduler, run at the next 09:00 (or immediately on request)
        ftype, fval = "event", "visibility.once"
    if times > 1 and frequency == "daily":
        ftype, fval = "every_x_hours", str(max(1, 24 // times))
    ev = r["evidence"] or {}
    keyword = ev.get("keyword") or (ev.get("keywords") or [None])[0]
    category = "articles" if (r["channel"] in (None, "blog") or r["apply_mode"] == "ai_content") else "social"
    params = {"content_project_id": _content_project(str(r["product_id"]), r["profile_name"]), "product_id": str(r["product_id"]),
              "keyword": keyword, "title": r["title"], "objective": r["detail"], "channel": r["channel"], "recommendation_id": str(r["id"]),
              "times_per_period": times, "frequency": frequency,
              "content_type": "social_post" if r["channel"] not in (None, "blog") else "article",
              "brief": ("Inclure : mots-clés ciblés, une étude ou des statistiques sourcées (ne jamais inventer de chiffre : citer la source "
                        "ou indiquer « donnée à compléter »), un comparatif objectif et une FAQ.")}
    mode = {"automatic": "automatic", "approval": "approval", "analysis": "analysis"}.get(autonomy, "approval")
    sid = fetch_one("""INSERT INTO public.tenant_schedulers (tenant_id, product_id, name, description, timezone, status, category, frequency_type,
                         frequency_value, params, mode, next_run_at, scheduler_kind, visibility_profile_id, recommendation_ids)
                       VALUES (%s,%s,%s,%s,'Europe/Paris','active',%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s::jsonb) RETURNING id""",
                    [tid, r["product_id"], r["title"][:200], r["detail"], category, ftype, fval, json.dumps(params), mode,
                     next_run("daily", "09:00", "Europe/Paris") if ftype == "event" else next_run(ftype, fval, "Europe/Paris"), kind, r["profile_id"], json.dumps([str(r["id"])])])[0]
    record_activity("scheduler.created", "scheduler", entity_type="tenant_schedulers", entity_id=sid,
                    description=f"Programmation {'intelligente' if kind == 'intelligent' else 'standard'} : {r['title'][:120]}")
    return str(sid)


def create_intelligent_watch(profile_id: str, product_id: str, name: str) -> str | None:
    """Intelligent mode: weekly re-audit that re-prioritises the plan from new observations."""
    from apps.licensing.services import check_quota
    from apps.scheduler.engine import next_run
    tid = get_context().tenant_id
    if fetch_one("""SELECT 1 FROM public.tenant_schedulers WHERE tenant_id = %s AND visibility_profile_id = %s AND category = 'seo'
                    AND scheduler_kind = 'intelligent' AND deleted_at IS NULL""", [tid, profile_id]):
        return None
    check_quota(tid, "scheduler.configurations")
    return str(fetch_one("""INSERT INTO public.tenant_schedulers (tenant_id, product_id, name, description, timezone, status, category,
                              frequency_type, frequency_value, params, mode, next_run_at, scheduler_kind, visibility_profile_id)
                            VALUES (%s,%s,%s,%s,'Europe/Paris','active','seo','weekly','0 07:00',%s::jsonb,'automatic',%s,'intelligent',%s) RETURNING id""",
                         [tid, product_id, f"Veille intelligente — {name}"[:200],
                          "Ré-audit hebdomadaire du site et des concurrents, recommandations re-priorisées automatiquement.",
                          json.dumps({"visibility_profile_id": profile_id}), next_run("weekly", "0 07:00", "Europe/Paris"), profile_id])[0])


# ───────────────────────────── assistant ─────────────────────────────
def assistant_reply(profile_id: str | None, message: str, history: list[dict], client_answers: dict | None = None) -> dict:
    """SEO/GEO assistant used during configuration. Works without AI (guided questionnaire); answers with AI when configured.
    Before the programme exists the answers travel with the client and are saved when the programme is created."""
    from apps.ai_providers.gateway import AINotConfigured, complete, wrap_untrusted
    keys = {k for k, _ in FUNDAMENTAL_QUESTIONS}
    answers = {k: str(v)[:2000] for k, v in (client_answers or {}).items() if k in keys and v}
    if profile_id:
        row = fetch_one("SELECT answers FROM public.visibility_profiles WHERE id = %s AND tenant_id = %s", [profile_id, get_context().tenant_id])
        answers = {**answers, **((row[0] if row else {}) or {})}
    asked = [k for k, _ in FUNDAMENTAL_QUESTIONS if k in answers]
    last_q = next((k for k, _ in FUNDAMENTAL_QUESTIONS if k not in answers), None)
    if last_q and message.strip() and history:
        answers[last_q] = message.strip()[:2000]
        asked.append(last_q)
        if profile_id:
            fetch_one("UPDATE public.visibility_profiles SET answers = %s::jsonb WHERE id = %s RETURNING 1", [json.dumps(answers), profile_id])
    nxt = next(((k, q) for k, q in FUNDAMENTAL_QUESTIONS if k not in answers), None)
    try:
        res = complete("visibility_assistant", [*[{"role": h["role"], "content": h["content"][:4000]} for h in history[-10:]
                                                  if h.get("role") in ("user", "assistant")],
                                                {"role": "user", "content": wrap_untrusted("user_message", message)}],
                       system=("Tu es l'assistant SEO et GEO de Growth IA. Tu aides l'utilisateur à configurer son programme de visibilité "
                               "(Google, Bing, ChatGPT, Claude, Gemini, Perplexity). Réponds en français, concrètement, en 6 phrases maximum. "
                               "Ne promets jamais de résultat chiffré. " + (f"Termine par cette question : « {nxt[1]} »" if nxt else "")),
                       max_tokens=600, untrusted=True, agent_code="visibility_assistant")
        reply, source = res.text, "ai"
    except AINotConfigured:
        reply = ("Merci, c'est noté. " if history else "Bonjour ! Je vais vous poser quelques questions essentielles pour préparer votre "
                 "programme de visibilité. ") + (nxt[1] if nxt else "Toutes les questions essentielles sont renseignées : vous pouvez lancer l'analyse.")
        source = "guided"
    return {"reply": reply, "source": source, "next_question": nxt[0] if nxt else None,
            "answered": len(asked), "total": len(FUNDAMENTAL_QUESTIONS), "answers": answers}


# ───────────────────────────── KPIs & AI visibility ─────────────────────────────
def kpis(product_id: str | None = None) -> dict:
    """Tenant home KPIs — only real sources; a KPI without source is returned as not_connected."""
    tid = get_context().tenant_id
    connected = {r["code"] for r in fetch_all_dict("""SELECT p.code FROM public.tenant_connector_accounts a
                                                        JOIN public.connector_providers p ON p.id = a.provider_id
                                                       WHERE a.tenant_id = %s AND a.deleted_at IS NULL AND a.status IN ('connected','tested')""", [tid])}
    gsc, ga = "google_search_console" in connected, "google_analytics" in connected
    last = fetch_one("""SELECT a.id, a.score, a.site_findings, a.finished_at FROM public.visibility_audits a
                         WHERE a.tenant_id = %s AND a.status = 'succeeded' ORDER BY a.finished_at DESC LIMIT 1""", [tid])
    prev = fetch_one("""SELECT a.score FROM public.visibility_audits a WHERE a.tenant_id = %s AND a.status = 'succeeded'
                         ORDER BY a.finished_at DESC OFFSET 1 LIMIT 1""", [tid])
    sitemap_count = sum(s.get("sitemap_urls_count", 0) for s in ((last[2] or {}).get("sites", []) if last else []))
    geo = fetch_one("""SELECT count(*) AS responses,
                              count(*) FILTER (WHERE EXISTS (SELECT 1 FROM public.ai_search_mentions m JOIN public.brand_entities b ON b.id = m.brand_entity_id
                                         WHERE m.response_id = r.id AND b.entity_type IN ('brand','product'))) AS with_mention,
                              count(*) FILTER (WHERE EXISTS (SELECT 1 FROM public.ai_search_citations c WHERE c.response_id = r.id AND c.domain IN
                                         (SELECT lower(primary_domain) FROM public.products pr WHERE pr.tenant_id = r.tenant_id AND pr.deleted_at IS NULL AND pr.primary_domain IS NOT NULL))) AS with_citation
                         FROM public.ai_search_responses r WHERE r.tenant_id = %s AND r.created_at > now() - interval '30 days'""", [tid])
    refdomains = fetch_one("""SELECT count(DISTINCT substring(source_url from '^[a-z]+://([^/:]+)')) FROM public.backlinks
                               WHERE tenant_id = %s AND deleted_at IS NULL AND lost_at IS NULL""", [tid])

    def k(code, label, value, status, source, trend=None, unit=None, note=None):
        return {"code": code, "label": label, "value": value, "status": status, "source": source, "trend": trend, "unit": unit, "note": note}

    responses = int(geo[0]) if geo else 0
    return {"kpis": [
        k("indexed_pages", "Pages indexées", None if not gsc else None, "connected" if gsc else "not_connected", "Google Search Console",
          note=None if gsc else (f"{sitemap_count} pages déclarées dans le sitemap (non équivalent à l'indexation)" if sitemap_count else None)),
        k("impressions", "Impressions Google", None, "connected" if gsc else "not_connected", "Google Search Console"),
        k("clicks", "Clics organiques", None, "connected" if gsc else "not_connected", "Google Search Console"),
        k("avg_position", "Position moyenne", None, "connected" if gsc else "not_connected", "Google Search Console"),
        k("organic_traffic", "Trafic organique", None, "connected" if ga else "not_connected", "Google Analytics 4"),
        k("referring_domains", "Domaines référents", int(refdomains[0]) if refdomains else 0, "observed", "Backlink Monitor (imports / connecteurs)"),
        k("ai_mention_rate", "AI Mention Rate", round(100 * geo[1] / responses) if responses else None, "observed" if responses else "no_data",
          "Tests GEO réellement exécutés (30 j)", unit="%", note=f"{responses} réponses IA analysées" if responses else "Aucun test IA exécuté"),
        k("ai_citation_rate", "AI Citation Rate", round(100 * geo[2] / responses) if responses else None, "observed" if responses else "no_data",
          "Tests GEO réellement exécutés (30 j)", unit="%"),
        k("organic_signups", "Inscriptions organiques", None, "connected" if ga else "not_connected", "Google Analytics 4 (événement d'inscription)"),
        k("conversion", "Conversion visiteurs → clients", None, "connected" if ga else "not_connected", "Google Analytics 4 + Stripe"),
        k("technical_score", "Score technique (dernier audit)", last[1] if last else None, "observed" if last else "no_data", "Audit Growth IA",
          trend=(last[1] - prev[0]) if last and prev and last[1] is not None and prev[0] is not None else None, unit="/100"),
    ], "last_audit_at": last[3] if last else None, "connectors": {"google_search_console": gsc, "google_analytics": ga}}


def ai_visibility_dashboard() -> dict:
    """Presence per AI engine from tests actually executed (observed), never estimated."""
    tid = get_context().tenant_id
    rows = fetch_all_dict("""SELECT coalesce(ru.engine, 'unknown') AS engine, count(*) AS responses,
                                    count(*) FILTER (WHERE EXISTS (SELECT 1 FROM public.ai_search_mentions m JOIN public.brand_entities b ON b.id = m.brand_entity_id
                                         WHERE m.response_id = r.id AND b.entity_type IN ('brand','product'))) AS mentions,
                                    count(*) FILTER (WHERE EXISTS (SELECT 1 FROM public.ai_search_citations c WHERE c.response_id = r.id AND c.domain IN
                                         (SELECT lower(primary_domain) FROM public.products pr WHERE pr.tenant_id = r.tenant_id AND pr.deleted_at IS NULL AND pr.primary_domain IS NOT NULL))) AS citations,
                                    max(r.created_at) AS last_test
                               FROM public.ai_search_responses r LEFT JOIN public.ai_search_runs ru ON ru.id = r.run_id
                              WHERE r.tenant_id = %s AND r.created_at > now() - interval '90 days'
                              GROUP BY 1 ORDER BY 2 DESC""", [tid])
    for r in rows:
        r["presence_rate"] = round(100 * r["mentions"] / r["responses"]) if r["responses"] else None
        r["nature"] = "observed"
    total = sum(r["responses"] for r in rows)
    return {"engines": rows, "responses": total,
            "mention_rate": round(100 * sum(r["mentions"] for r in rows) / total) if total else None,
            "citations": sum(r["citations"] for r in rows),
            "questions": fetch_all_dict("""SELECT q.id, q.question, q.intent, q.language, q.source, q.is_active FROM public.ai_visibility_questions q
                                            WHERE q.tenant_id = %s AND q.deleted_at IS NULL ORDER BY q.created_at DESC LIMIT 200""", [tid]),
            "engines_without_api": ["Google AI Overviews", "Microsoft Copilot"],
            "disclaimer": "Résultats observés sur les tests réellement exécutés via API autorisées ; ils varient selon la question, la langue, "
                          "la localisation et le moment. Aucun chiffre n'est estimé."}


def seed_questions(profile_id: str) -> int:
    """Builds the question library for the sector from the profile (deterministic templates, + AI suggestions if configured)."""
    tid = get_context().tenant_id
    row = fetch_one("SELECT name, sector, offer, site_urls FROM public.visibility_profiles WHERE id = %s AND tenant_id = %s", [profile_id, tid])
    if not row:
        raise BusinessError("Profil introuvable", "not_found", status_code=404)
    name, sector, offer, _ = row
    topic = sector or offer or name
    templates = [(f"Quel est le meilleur logiciel pour {topic} ?", "discovery"), (f"Quelles sont les alternatives à {name} ?", "alternative"),
                 (f"Comparatif des outils SaaS de {topic} en 2026", "comparison"), (f"Comment choisir un outil de {topic} ?", "problem"),
                 (f"Que penses-tu de {name} ?", "brand"), (f"Quels outils recommandes-tu pour {topic} en France ?", "discovery")]
    n = 0
    for q, intent in templates:
        if not fetch_one("SELECT 1 FROM public.ai_visibility_questions WHERE tenant_id = %s AND profile_id = %s AND question = %s AND deleted_at IS NULL",
                         [tid, profile_id, q]):
            fetch_one("""INSERT INTO public.ai_visibility_questions (tenant_id, profile_id, question, intent, source)
                         VALUES (%s,%s,%s,%s,'library') RETURNING id""", [tid, profile_id, q, intent])
            n += 1
    return n


def audit_report(aid: str) -> dict:
    tid = get_context().tenant_id
    a = fetch_all_dict("""SELECT a.*, p.name AS profile_name, p.site_urls FROM public.visibility_audits a
                            JOIN public.visibility_profiles p ON p.id = a.profile_id WHERE a.id = %s AND a.tenant_id = %s""", [aid, tid])
    if not a:
        raise BusinessError("Audit introuvable", "not_found", status_code=404)
    a = a[0]
    recs = fetch_all_dict("""SELECT id, category, code, title, detail, priority, impact, effort, apply_mode, channel, status, frequency,
                                    times_per_period, evidence, applied_result FROM public.visibility_recommendations
                              WHERE audit_id = %s AND deleted_at IS NULL ORDER BY CASE priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1
                              WHEN 'medium' THEN 2 ELSE 3 END, created_at""", [aid])
    assets = fetch_all_dict("""SELECT id, asset_type, filename, content_type, length(content) AS size FROM public.visibility_generated_assets
                                WHERE audit_id = %s AND deleted_at IS NULL ORDER BY asset_type""", [aid])
    roadmap = fetch_all_dict("""SELECT id, phase, area, title, detail, priority, status, kpi FROM public.tenant_roadmap_items
                                 WHERE audit_id = %s AND deleted_at IS NULL ORDER BY CASE phase WHEN 'now' THEN 0 WHEN 'next' THEN 1 ELSE 2 END,
                                 CASE priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END""", [aid])
    return {"audit": a, "recommendations": recs, "assets": assets, "roadmap": roadmap, "channels": CHANNELS, "kpis": kpis()}


# ───────────────────────────── competitor discovery & execution tracking ─────────────────────────────
def discover_competitors(site_url: str, name: str | None = None, sector: str | None = None) -> dict:
    """Candidates shown to the user right after the site link is entered, each labelled with where it comes from:
    site_mentions (observed on the site), known (already declared in another programme), ai_suggested (to be verified)."""
    url = site_url if "://" in site_url else f"https://{site_url}"
    own = urlparse(url).netloc.lower().removeprefix("www.")
    ua = getattr(settings, "CRAWLER_USER_AGENT", "GrowthIA-Bot/1.0")
    out: dict[str, dict] = {}

    def key(c: dict) -> str:
        return urlparse(c.get("url") or "").netloc.lower().removeprefix("www.") or c["name"].lower()

    for c in analyzer.find_competitor_mentions(url, ua):
        out.setdefault(key(c), c)
    rows = fetch_all_dict("SELECT competitors FROM public.visibility_profiles WHERE tenant_id = %s AND deleted_at IS NULL",
                          [get_context().tenant_id])
    for r in rows:
        for c in r["competitors"] or []:
            if isinstance(c, dict) and c.get("name"):
                out.setdefault(key(c), {"name": c["name"], "url": c.get("url") or "", "source": "known",
                                        "evidence": ["Déjà déclaré dans un autre programme"], "mentions": 0})
    ai_available = True
    home = analyzer._get(requests.Session(), url, timeout=10)
    keywords = []
    if home is not None and home.status_code < 400:
        info = analyzer.inspect_home(home.text, home.url)
        keywords = analyzer.extract_keywords([(info["text"], 1.0), (info.get("title") or "", 3.0)], top=15)
        name = name or (info.get("title") or own).split("|")[0].split("-")[0].strip()[:80]
    suggestions = _ai_suggest_competitors(name or own, sector, None, keywords, url, None)
    if not suggestions:
        from apps.ai_providers.gateway import routes
        ai_available = bool(routes("visibility_competitors", get_context().tenant_id))
    for c in suggestions:
        c = {**c, "evidence": ["Suggéré par l'IA, à vérifier"], "mentions": 0}
        out.setdefault(key(c), c)
    cands = [c for k, c in out.items() if k and k != own][:12]
    return {"site": url, "name": name, "candidates": cands, "ai_available": ai_available,
            "note": None if cands else "Aucun concurrent n'est cité sur le site. Ajoutez-les manuellement ou configurez un fournisseur IA pour des suggestions."}


def _run_state(run: dict | None, rec: dict) -> tuple[str, int, str]:
    if rec["status"] in ("accepted", "applied") and rec["apply_mode"] in ("generated_file", "manual"):
        return ("ready", 100, "Fichier prêt à déployer" if rec["apply_mode"] == "generated_file" else "Ajouté à la roadmap")
    if not run:
        return ("planned", 0, "Programmé")
    st, steps = run["status"], run["steps"] or 0
    if st == "queued":
        return ("queued", 10, "En file d'attente")
    if st in ("running", "retrying"):
        return ("running", min(90, 30 + 20 * steps), "Exécution en cours")
    if st == "succeeded":
        if (run.get("result") or {}).get("pending_approval"):
            return ("awaiting_approval", 90, "En attente de votre validation avant publication")
        return ("succeeded", 100, "Exécuté")
    if st == "cancelled":
        return ("cancelled", 0, run.get("error_message") or "Annulé")
    return ("failed", 100, run.get("error_message") or "Échec")


def execution_status(audit_id: str | None) -> list[dict]:
    """Progress of validated actions: the latest scheduler run of each one (queued → running → succeeded / awaiting approval / failed)."""
    tid = get_context().tenant_id
    rows = fetch_all_dict("""
        SELECT r.id, r.title, r.status, r.apply_mode, r.channel, r.frequency, r.times_per_period, r.applied_result,
               s.id AS scheduler_id, s.next_run_at, s.frequency_type, s.mode, s.status AS scheduler_status,
               lr.id AS run_id, lr.status AS run_status, lr.started_at, lr.completed_at, lr.error_message, lr.result, lr.triggered_by,
               (SELECT count(*) FROM public.scheduler_execution_steps st WHERE st.run_id = lr.id) AS steps
          FROM public.visibility_recommendations r
          LEFT JOIN public.tenant_schedulers s ON s.id = nullif(r.applied_result->>'scheduler_id', '')::uuid AND s.deleted_at IS NULL
          LEFT JOIN LATERAL (SELECT * FROM public.scheduler_execution_runs x WHERE x.scheduler_id = s.id ORDER BY x.created_at DESC LIMIT 1) lr ON true
         WHERE r.tenant_id = %s AND r.deleted_at IS NULL AND r.status IN ('accepted','scheduled','applied')
           AND (%s::uuid IS NULL OR r.audit_id = %s::uuid)
         ORDER BY r.updated_at DESC NULLS LAST LIMIT 200""", [tid, audit_id, audit_id])
    out = []
    for r in rows:
        run = None if not r["run_id"] else {"status": r["run_status"], "steps": r["steps"], "result": r["result"], "error_message": r["error_message"]}
        state, pct, label = _run_state(run, r)
        res = r["result"] or {}
        out.append({"id": str(r["id"]), "title": r["title"], "apply_mode": r["apply_mode"], "channel": r["channel"], "frequency": r["frequency"],
                    "times_per_period": r["times_per_period"], "scheduler_id": str(r["scheduler_id"]) if r["scheduler_id"] else None,
                    "next_run_at": r["next_run_at"] if r["frequency_type"] != "event" or not r["run_id"] else None,
                    "autonomy": r["mode"], "run_id": str(r["run_id"]) if r["run_id"] else None, "state": state, "progress": pct, "label": label,
                    "started_at": r["started_at"], "completed_at": r["completed_at"], "content_id": res.get("content_id"),
                    "can_run_now": bool(r["scheduler_id"]) and state not in ("queued", "running") and r["scheduler_status"] == "active"})
    return out


def run_now(rec_id: str) -> dict:
    from apps.scheduler.engine import enqueue_run
    row = fetch_one("""SELECT applied_result->>'scheduler_id' FROM public.visibility_recommendations
                        WHERE id = %s AND tenant_id = %s AND deleted_at IS NULL""", [rec_id, get_context().tenant_id])
    if not row or not row[0]:
        raise BusinessError("Cette action n'a pas d'exécution programmée", "not_schedulable")
    run_id = enqueue_run(row[0], "manual")
    if not run_id:
        raise BusinessError("La programmation est en pause ou supprimée", "scheduler_inactive")
    record_audit("visibility.run_now", "visibility", entity_type="visibility_recommendations", entity_id=rec_id, after={"run_id": run_id})
    return {"run_id": run_id}
