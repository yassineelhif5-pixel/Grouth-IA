"""Prospect hunting: keyword scan of the product site, company discovery from authorised public sources, generic
contacts published by companies on their own site, optional licensed enrichment provider, explainable scoring,
pre-filled commercial e-mail reviewed by a human before sending, tracked trial link and one-click unsubscribe.

Sources and limits (deliberate, see docs/modules/PROSPECT_HUNT.md):
- Companies: French public API « Recherche d'entreprises » (data.gouv / DINUM, open data, no key). Company officers
  (dirigeants) are public data of the national company register; they are stored without any e-mail address.
- Company sites: only pages allowed by robots.txt, only role-based addresses on the company's own domain
  (contact@, info@, sales@…). Nominative addresses are never harvested from web pages.
- LinkedIn and other social networks are not scraped (their terms forbid it).
- Named people with professional e-mails: only through a licensed B2B provider configured by the tenant (Hunter).
- Every e-mail is drafted, shown, possibly edited, then sent one by one by a user; it carries the sender identity
  and an unsubscribe link; suppressed / opted-out addresses are refused by the Email Center.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from urllib import robotparser
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from django.conf import settings
from django.core import signing
from django.db import transaction

from apps.audit.services import record_activity, record_audit
from apps.core.context import get_context
from apps.core.db import fetch_all_dict, fetch_one
from apps.core.exceptions import BusinessError
from apps.licensing.services import check_quota

COMPANY_API = "https://recherche-entreprises.api.gouv.fr/search"
LINK_NAMESPACE = "growth.prospects.hunt"  # signing salt (namespace), the key is SECRET_KEY
ROLE_ADDRESSES = ("contact", "info", "infos", "hello", "bonjour", "commercial", "sales", "vente", "ventes", "partenariat",
                  "partenariats", "partners", "business", "marketing", "communication", "direction", "accueil", "service.client")
CONTACT_PATHS = ("/", "/contact", "/contact/", "/contactez-nous", "/nous-contacter", "/contact-us", "/mentions-legales", "/a-propos")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
WORD_RE = re.compile(r"[a-zàâäçéèêëîïôöûùüÿœæ][a-zàâäçéèêëîïôöûùüÿœæ0-9'-]{2,}", re.I)
STOPWORDS = set("""
au aux avec ce ces cette dans de des du elle en et eux il ils je la le les leur leurs lui ma mais me même mes moi mon ne nos
notre nous on ou où par pas pour qu que qui sa se ses son sur ta te tes toi ton tu un une vos votre vous est sont été être
avoir fait faire plus moins très tout tous toute toutes aussi comme ainsi alors donc car si sans sous entre vers chez dont
cela ceci ici là bien encore déjà après avant depuis pendant selon chaque autre autres quel quelle quels quelles peut peuvent
nos votre vos notre leurs the and for with that this from your you are our not but can all any has have was were will
more most about into over than then them they their there what when which who how also only just get use using new
accueil contact menu page site cookies cookie mentions légales politique confidentialité droits réservés copyright savoir
""".split())
CATEGORY_LABEL = {"GE": "Grand groupe", "ETI": "Entreprise de taille intermédiaire", "PME": "PME"}
TRANCHE_EMPLOYEES = {"00": 0, "01": 1, "02": 3, "03": 6, "11": 10, "12": 20, "21": 50, "22": 100, "31": 200, "32": 250,
                     "41": 500, "42": 1000, "51": 2000, "52": 5000, "53": 10000}
TREND_MODIFIERS = ("logiciel", "outil", "IA", "automatisation", "gratuit", "comparatif", "alternative", "2026", "meilleur", "SaaS")


# ───────────────────────────── fetching (robots.txt respected) ─────────────────────────────
class Fetcher:
    def __init__(self, timeout: float = 12):
        self.timeout = timeout
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": settings.CRAWLER_USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
        self._robots: dict[str, robotparser.RobotFileParser] = {}

    def allowed(self, url: str) -> bool:
        p = urlparse(url)
        root = f"{p.scheme}://{p.netloc}"
        if root not in self._robots:
            rp = robotparser.RobotFileParser()
            try:
                r = self.s.get(root + "/robots.txt", timeout=self.timeout)
                rp.parse(r.text.splitlines() if r.status_code == 200 else [])
            except requests.RequestException:
                rp.parse([])
            self._robots[root] = rp
        return self._robots[root].can_fetch(settings.CRAWLER_USER_AGENT, url)

    def html(self, url: str) -> str | None:
        if not self.allowed(url):
            return None
        try:
            r = self.s.get(url, timeout=self.timeout, allow_redirects=True)
        except requests.RequestException:
            return None
        if r.status_code != 200 or "html" not in r.headers.get("Content-Type", "html"):
            return None
        return r.text[:2_000_000]


def _site_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        raise BusinessError("Indiquez l'adresse du site à analyser", "url_required")
    return url if "://" in url else f"https://{url}"


# ───────────────────────────── 1. keyword scan ─────────────────────────────
def _keywords_from_html(html: str) -> Counter:
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "noscript", "svg", "nav", "footer"]):
        t.decompose()
    weighted: Counter = Counter()

    def add(text: str, w: int):
        words = [x.lower().strip("'-") for x in WORD_RE.findall(text or "")]
        words = [x for x in words if x not in STOPWORDS and not x.isdigit() and len(x) > 2]
        for x in words:
            weighted[x] += w
        for a, b in zip(words, words[1:], strict=False):
            weighted[f"{a} {b}"] += w
    add(soup.title.get_text(" ") if soup.title else "", 4)
    meta = soup.find("meta", attrs={"name": "description"})
    add(meta.get("content", "") if meta else "", 3)
    for h in soup.find_all(["h1", "h2", "h3"]):
        add(h.get_text(" "), 2)
    add(soup.get_text(" "), 1)
    return weighted


def scan_keywords(url: str, max_pages: int = 5) -> dict:
    """Keywords really present on the site (title, meta, headings and text, weighted) + suggested keywords to target."""
    start = _site_url(url)
    f = Fetcher()
    host = urlparse(start).netloc.lower()
    html = f.html(start)
    if html is None:
        raise BusinessError("Le site n'a pas pu être lu (inaccessible ou interdit par robots.txt)", "site_unreachable", status_code=422)
    pages, total = [start], _keywords_from_html(html)
    links = [urljoin(start, a.get("href")) for a in BeautifulSoup(html, "html.parser").find_all("a", href=True)]
    for link in dict.fromkeys(u.split("#")[0] for u in links):
        if len(pages) >= max_pages:
            break
        if urlparse(link).netloc.lower() != host or link in pages or re.search(r"\.(pdf|jpg|png|zip|svg)$", link, re.I):
            continue
        h = f.html(link)
        if h:
            pages.append(link)
            total.update(_keywords_from_html(h))
    # a bigram must appear at least twice to count; single words keep their weight
    found = [{"keyword": k, "weight": w} for k, w in total.most_common(200) if (" " not in k or w >= 2)][:30]
    suggestions, method = suggest_keywords([k["keyword"] for k in found[:15]], start)
    record_activity("prospects.keywords_scanned", "prospects", description=f"Mots-clés analysés sur {host}",
                    metadata={"pages": len(pages), "keywords": len(found)})
    return {"url": start, "pages_scanned": pages, "keywords": found, "suggestions": suggestions, "suggestions_method": method}


def suggest_keywords(found: list[str], url: str) -> tuple[list[dict], str]:
    from apps.ai_providers.gateway import AINotConfigured, complete, wrap_untrusted
    try:
        res = complete("prospects.keywords", [{"role": "user", "content": wrap_untrusted(
            "site", f"Site : {url}\nMots-clés trouvés : {', '.join(found)}")}], untrusted=True, max_tokens=900, temperature=0.6,
            system=("Tu es expert SEO et growth B2B en France. Propose 12 nouveaux mots-clés à fort potentiel (tendances, longue "
                    "traîne, intention d'achat) que ce site ne couvre pas encore. Réponds uniquement en JSON : "
                    '[{"keyword": "...", "intent": "achat|information|comparaison", "why": "..."}]'))
        data = json.loads(res.text[res.text.find("["): res.text.rfind("]") + 1])
        return [{"keyword": str(d["keyword"])[:120], "intent": str(d.get("intent", ""))[:40], "why": str(d.get("why", ""))[:300]}
                for d in data if d.get("keyword")][:15], "ai"
    except (AINotConfigured, ValueError, KeyError, TypeError):
        pass
    heads = [k for k in found if " " not in k][:4] or found[:4]
    out = []
    for h in heads:
        for m in TREND_MODIFIERS:
            kw = f"{m} {h}" if m in ("logiciel", "outil", "meilleur", "comparatif", "alternative") else f"{h} {m}"
            if kw not in found:
                out.append({"keyword": kw, "intent": "achat" if m in ("logiciel", "outil", "SaaS", "gratuit") else "comparaison",
                            "why": "Combinaison d'un mot-clé du site avec un modificateur de recherche fréquent"})
    return out[:15], "rules"


# ───────────────────────────── 2. companies (open data) ─────────────────────────────
def search_companies(query: str, category: str | None = None, page: int = 1) -> dict:
    """French companies from the public « Recherche d'entreprises » API (open data). Nothing is stored here."""
    from apps.integrations.gateway import http
    if not (query or "").strip():
        raise BusinessError("Indiquez un mot-clé ou un secteur", "query_required")
    params = {"q": query.strip()[:200], "page": max(1, int(page)), "per_page": 20, "etat_administratif": "A"}
    if category in CATEGORY_LABEL:
        params["categorie_entreprise"] = category
    data = http("GET", COMPANY_API, provider="recherche_entreprises", operation="search", params=params, timeout=20).json()
    out = []
    for r in data.get("results", []):
        siege = r.get("siege") or {}
        out.append({
            "siren": r.get("siren"), "name": r.get("nom_complet") or r.get("nom_raison_sociale"),
            "category": r.get("categorie_entreprise"), "category_label": CATEGORY_LABEL.get(r.get("categorie_entreprise") or "", "Non renseignée"),
            "naf": r.get("activite_principale"), "naf_label": r.get("libelle_activite_principale"),
            "employees": TRANCHE_EMPLOYEES.get(r.get("tranche_effectif_salarie") or ""),
            "city": siege.get("libelle_commune"), "postal_code": siege.get("code_postal"),
            "officers": [{"name": " ".join(x for x in (d.get("prenoms"), d.get("nom")) if x) or d.get("denomination"), "role": d.get("qualite")}
                         for d in (r.get("dirigeants") or [])[:5]],
        })
    return {"results": out, "total": data.get("total_results", len(out)), "page": params["page"], "source": "recherche-entreprises.api.gouv.fr"}


def add_companies(items: list[dict], product_id: str | None, domain_by_siren: dict | None = None) -> dict:
    """Stores selected companies as prospects (dedup by SIREN), officers as contacts without e-mail, then scores them."""
    tid = get_context().tenant_id
    check_quota(tid, "prospects.max", len(items))
    src = fetch_one("SELECT id FROM public.prospect_sources WHERE tenant_id = %s AND name = %s AND deleted_at IS NULL",
                    [tid, "Recherche d'entreprises (open data)"])
    src = src[0] if src else fetch_one("""INSERT INTO public.prospect_sources (tenant_id, name, source_type) VALUES (%s,%s,'api') RETURNING id""",
                                       [tid, "Recherche d'entreprises (open data)"])[0]
    created, existing, ids = 0, 0, []
    with transaction.atomic():
        for it in items:
            siren = str(it.get("siren") or "").strip()
            if not siren or not it.get("name"):
                continue
            row = fetch_one("""SELECT p.id FROM public.prospects p JOIN public.prospect_companies c ON c.id = p.company_id
                                WHERE p.tenant_id = %s AND c.data->>'siren' = %s AND p.deleted_at IS NULL LIMIT 1""", [tid, siren])
            if row:
                existing += 1
                ids.append(str(row[0]))
                continue
            data = {k: it.get(k) for k in ("siren", "category", "category_label", "naf", "naf_label", "city", "postal_code", "officers")}
            domain = ((domain_by_siren or {}).get(siren) or it.get("domain") or "").strip().lower() or None
            comp = fetch_one("""INSERT INTO public.prospect_companies (tenant_id, name, domain, industry, size_employees, country_code, data, source)
                                VALUES (%s,%s,%s,%s,%s,'FR',%s::jsonb,'recherche_entreprises') RETURNING id""",
                             [tid, it["name"][:300], domain, (it.get("naf_label") or "")[:200] or None, it.get("employees"), json.dumps(data)])[0]
            pid = str(fetch_one("""INSERT INTO public.prospects (tenant_id, company_id, source_id, product_id, status, source_detail)
                                   VALUES (%s,%s,%s,%s,'new_lead','Recherche d''entreprises (open data)') RETURNING id""",
                                [tid, comp, src, product_id])[0])
            for o in (it.get("officers") or [])[:5]:
                if o.get("name"):
                    parts = o["name"].split(" ", 1)
                    fetch_one("""INSERT INTO public.prospect_contacts (tenant_id, prospect_id, first_name, last_name, job_title, consent_status)
                                 VALUES (%s,%s,%s,%s,%s,'unknown') RETURNING id""",
                              [tid, pid, parts[0][:100], (parts[1] if len(parts) > 1 else "")[:100] or None, (o.get("role") or "Dirigeant")[:200]])
            created += 1
            ids.append(pid)
    for pid in ids:
        score_prospect(pid)
    record_audit("prospects.hunt_added", "prospects", entity_type="prospect_sources", entity_id=src, after={"created": created, "existing": existing})
    return {"created": created, "already_known": existing, "prospect_ids": ids}


# ───────────────────────────── 3. contacts ─────────────────────────────
def is_role_address(email: str, domain: str) -> bool:
    local, _, host = email.lower().partition("@")
    host_ok = host == domain or host.endswith("." + domain) or domain.endswith("." + host)
    return host_ok and any(local == r or local.startswith(r + ".") or local.startswith(r + "-") for r in ROLE_ADDRESSES)


def find_site_contacts(prospect_id: str, domain: str | None = None) -> dict:
    """Role-based addresses (contact@, info@…) the company publishes on its own site, robots.txt respected."""
    tid = get_context().tenant_id
    row = fetch_one("""SELECT c.id, c.domain FROM public.prospects p JOIN public.prospect_companies c ON c.id = p.company_id
                        WHERE p.id = %s AND p.tenant_id = %s""", [prospect_id, tid])
    if not row:
        raise BusinessError("prospect not found", "not_found", status_code=404)
    company_id, raw = row[0], (domain or row[1] or "").strip().lower()
    parsed = urlparse(raw if "://" in raw else f"https://{raw}") if raw else None
    dom = parsed.netloc.removeprefix("www.") if parsed else ""
    if not dom:
        raise BusinessError("Indiquez le site web de l'entreprise (ex. entreprise.fr)", "domain_required")
    if domain:
        fetch_one("UPDATE public.prospect_companies SET domain = %s WHERE id = %s RETURNING 1", [dom, company_id])
    f, emails, pages = Fetcher(), set(), []
    for path in CONTACT_PATHS:
        url = f"{parsed.scheme}://{parsed.netloc}{path}"
        html = f.html(url)
        if not html:
            continue
        pages.append(url)
        found = set(EMAIL_RE.findall(html)) | {m.removeprefix("mailto:").split("?")[0] for m in re.findall(r"mailto:[^\"'>\s]+", html)}
        emails |= {e.lower() for e in found if is_role_address(e, dom)}
    added = 0
    for e in sorted(emails)[:5]:
        if fetch_one("SELECT 1 FROM public.prospect_contacts WHERE tenant_id = %s AND prospect_id = %s AND lower(email) = %s AND deleted_at IS NULL",
                     [tid, prospect_id, e]):
            continue
        fetch_one("""INSERT INTO public.prospect_contacts (tenant_id, prospect_id, email, job_title, consent_status)
                     VALUES (%s,%s,%s,'Adresse générique publiée par l''entreprise','legitimate_interest') RETURNING id""", [tid, prospect_id, e])
        added += 1
    score_prospect(prospect_id)
    return {"domain": dom, "pages_checked": pages, "emails": sorted(emails), "added": added}


def enrich_with_provider(prospect_id: str) -> dict:
    """Named professional contacts from a licensed B2B data provider (Hunter domain search), when configured."""
    from apps.integrations.gateway import http
    key = getattr(settings, "HUNTER_API_KEY", "")
    if not key:
        raise BusinessError("Aucun fournisseur de contacts professionnels n'est configuré (clé Hunter à ajouter)",
                            "enrichment_not_configured", status_code=409)
    tid = get_context().tenant_id
    dom = fetch_one("""SELECT c.domain FROM public.prospects p JOIN public.prospect_companies c ON c.id = p.company_id
                        WHERE p.id = %s AND p.tenant_id = %s""", [prospect_id, tid])
    if not dom or not dom[0]:
        raise BusinessError("Renseignez d'abord le site de l'entreprise", "domain_required")
    data = http("GET", "https://api.hunter.io/v2/domain-search", provider="hunter", operation="domain_search",
                params={"domain": dom[0], "type": "personal", "limit": 10, "api_key": key}).json().get("data", {})
    added = 0
    for e in data.get("emails", []):
        addr = (e.get("value") or "").lower()
        if not addr or (e.get("confidence") or 0) < 70:
            continue
        if fetch_one("SELECT 1 FROM public.prospect_contacts WHERE tenant_id = %s AND lower(email) = %s AND deleted_at IS NULL", [tid, addr]):
            continue
        fetch_one("""INSERT INTO public.prospect_contacts (tenant_id, prospect_id, first_name, last_name, email, job_title, linkedin_url, consent_status)
                     VALUES (%s,%s,%s,%s,%s,%s,%s,'legitimate_interest') RETURNING id""",
                  [tid, prospect_id, e.get("first_name"), e.get("last_name"), addr, e.get("position"), e.get("linkedin")])
        added += 1
    score_prospect(prospect_id)
    return {"added": added, "provider": "hunter"}


# ───────────────────────────── 4. scoring ─────────────────────────────
DECISION_ROLES = ("président", "president", "directeur", "director", "ceo", "dg", "gérant", "gerant", "fondateur", "founder",
                  "marketing", "commercial", "sales", "cmo", "cto", "digital", "growth", "communication")


def score_prospect(prospect_id: str) -> dict:
    """Explainable interest score (0-100): company size, sector fit with the product, decision makers, reachable e-mail.
    When an AI model is routed for 'prospects.scoring', its assessment is blended in and its reasons are kept."""
    tid = get_context().tenant_id
    p = fetch_one("""SELECT c.name, c.size_employees, c.industry, coalesce(c.data,'{}'), pr.name, coalesce(pr.description,''), coalesce(pr.icp,'{}')
                       FROM public.prospects p LEFT JOIN public.prospect_companies c ON c.id = p.company_id
                       LEFT JOIN public.products pr ON pr.id = p.product_id WHERE p.id = %s AND p.tenant_id = %s""", [prospect_id, tid])
    if not p:
        raise BusinessError("prospect not found", "not_found", status_code=404)
    name, employees, industry, data, product_name, product_desc, icp = p
    contacts = fetch_all_dict("SELECT email, job_title FROM public.prospect_contacts WHERE prospect_id = %s AND deleted_at IS NULL", [prospect_id])
    factors = []

    def f(label, pts, max_pts, detail):
        factors.append({"factor": label, "points": pts, "max": max_pts, "detail": detail})
        return pts
    cat = (data or {}).get("category")
    size_pts = {"GE": 30, "ETI": 24, "PME": 15}.get(cat, 8 if employees else 0)
    total = f("Taille", size_pts, 30, CATEGORY_LABEL.get(cat or "", f"{employees} salariés" if employees else "Inconnue"))
    terms = {w for w in WORD_RE.findall(f"{product_name or ''} {product_desc} {' '.join(icp.get('industries', []))}".lower()) if w not in STOPWORDS}
    sector = (industry or "").lower()
    hit = [t for t in terms if t in sector]
    total += f("Secteur", 25 if hit or any(i.lower() in sector for i in icp.get("industries", [])) else (8 if industry else 0), 25,
               industry or "Non renseigné")
    deciders = [c for c in contacts if c.get("job_title") and any(r in c["job_title"].lower() for r in DECISION_ROLES)]
    total += f("Décideurs identifiés", min(20, 10 * len(deciders)), 20, ", ".join(c["job_title"] for c in deciders[:3]) or "Aucun")
    named = [c for c in contacts if c.get("email") and not (c.get("job_title") or "").startswith("Adresse générique")]
    generic = [c for c in contacts if c.get("email") and c not in named]
    total += f("Joignable par e-mail", 25 if named else (12 if generic else 0), 25,
               "Contact nominatif" if named else ("Adresse générique" if generic else "Aucune adresse"))
    method, reasons = "hunt-rules-v1", None
    from apps.ai_providers.gateway import AINotConfigured, complete, wrap_untrusted
    try:
        res = complete("prospects.scoring", [{"role": "user", "content": wrap_untrusted("prospect", json.dumps({
            "entreprise": name, "secteur": industry, "categorie": cat, "salaries": employees, "contacts": [c.get("job_title") for c in contacts],
            "produit": product_name, "description_produit": product_desc[:1500]}, ensure_ascii=False))}], untrusted=True, max_tokens=400, temperature=0.2,
            system='Évalue de 0 à 100 l\'intérêt probable de cette entreprise pour le produit. JSON uniquement : {"score": 0-100, "reasons": "une phrase"}')
        j = json.loads(res.text[res.text.find("{"): res.text.rfind("}") + 1])
        total, method, reasons = round(0.5 * total + 0.5 * float(j["score"])), "hunt-ai-v1", str(j.get("reasons", ""))[:500]
    except (AINotConfigured, ValueError, KeyError, TypeError):
        pass
    score = max(0, min(100, round(total)))
    summary = reasons or "; ".join(f"{x['factor']} : {x['detail']}" for x in factors if x["points"])
    with transaction.atomic():
        fetch_one("UPDATE public.prospects SET score = %s, confidence = %s, need_detected = %s WHERE id = %s RETURNING 1",
                  [score, 100 if contacts else 60, summary[:1000], prospect_id])
        fetch_one("""INSERT INTO public.prospect_scores (tenant_id, prospect_id, score, model_version, factors)
                     VALUES (%s,%s,%s,%s,%s::jsonb) RETURNING id""", [tid, prospect_id, score, method, json.dumps(factors)])
    return {"score": score, "method": method, "factors": factors, "summary": summary}


# ───────────────────────────── 5. e-mail ─────────────────────────────
def make_token(kind: str, prospect_id: str, contact_id: str | None = None) -> str:
    return signing.dumps({"k": kind, "t": get_context().tenant_id, "p": prospect_id, "c": contact_id}, salt=LINK_NAMESPACE, compress=True)


def read_token(token: str, kind: str) -> dict:
    try:
        d = signing.loads(token, salt=LINK_NAMESPACE, max_age=60 * 60 * 24 * 365)
    except signing.BadSignature as e:
        raise BusinessError("Lien invalide ou expiré", "invalid_link", status_code=404) from e
    if d.get("k") != kind:
        raise BusinessError("Lien invalide", "invalid_link", status_code=404)
    return d


def draft_email(prospect_id: str, contact_id: str | None = None) -> dict:
    """Commercial e-mail pre-filled for review: short presentation, tracked trial link, sender identity, unsubscribe link."""
    tid = get_context().tenant_id
    p = fetch_one("""SELECT c.name, c.industry, coalesce(c.data,'{}'), pr.name, coalesce(pr.description,''), coalesce(pr.url, pr.primary_domain), t.name
                       FROM public.prospects p LEFT JOIN public.prospect_companies c ON c.id = p.company_id
                       LEFT JOIN public.products pr ON pr.id = p.product_id JOIN public.tenants t ON t.id = p.tenant_id
                      WHERE p.id = %s AND p.tenant_id = %s""", [prospect_id, tid])
    if not p:
        raise BusinessError("prospect not found", "not_found", status_code=404)
    company, industry, _data, product, desc, _url, sender_org = p
    contacts = fetch_all_dict("""SELECT id, first_name, last_name, email, job_title, consent_status FROM public.prospect_contacts
                                  WHERE prospect_id = %s AND deleted_at IS NULL AND email IS NOT NULL AND consent_status <> 'opted_out'
                                  ORDER BY (job_title LIKE 'Adresse générique%%'), created_at""", [prospect_id])
    contact = next((c for c in contacts if str(c["id"]) == str(contact_id)), contacts[0] if contacts else None)
    product = product or "GrowthAI"
    api = settings.PUBLIC_API_URL.rstrip("/")
    cid = str(contact["id"]) if contact else None
    trial = f"{api}/api/v1/public/prospects/go/{make_token('go', prospect_id, cid)}"
    unsub = f"{api}/api/v1/public/prospects/unsubscribe/{make_token('unsub', prospect_id, cid)}"
    hello = f"Bonjour {contact['first_name']}," if contact and contact.get("first_name") else "Bonjour,"
    pitch = (desc.strip().split("\n")[0][:400] if desc.strip() else
             f"{product} est une plateforme SaaS qui automatise votre croissance : SEO, visibilité dans les moteurs d'IA (GEO), "
             "contenus, réseaux sociaux et prospection intelligente, pilotés par l'IA depuis un seul espace.")
    subject = f"{company} : accélérer votre croissance avec {product}" if company else f"Découvrez {product}"
    intro = (f"En découvrant {company}" + (f", acteur du secteur « {industry.lower()} »," if industry else "") +
             " j'ai pensé que nos outils pourraient vous faire gagner un temps précieux.") if company else "Je me permets de vous présenter notre solution."
    from apps.ai_providers.gateway import AINotConfigured, complete, wrap_untrusted
    method = "template"
    try:
        res = complete("prospects.email_draft", [{"role": "user", "content": wrap_untrusted("prospect", json.dumps({
            "entreprise": company, "secteur": industry, "contact": contact.get("job_title") if contact else None, "produit": product,
            "description": pitch}, ensure_ascii=False))}], untrusted=True, max_tokens=500, temperature=0.5,
            system=("Rédige en français l'introduction (3 phrases maximum, vouvoiement, ton professionnel et chaleureux, sans promesse "
                    "chiffrée inventée) d'un e-mail de prospection B2B qui présente le potentiel du produit pour cette entreprise. "
                    "Texte brut uniquement, sans formule de politesse ni signature."))
        if res.text.strip():
            intro, method = res.text.strip()[:1200], "ai"
    except (AINotConfigured, ValueError):
        pass
    body = (f"{hello}\n\n{intro}\n\n{pitch}\n\n"
            f"Je vous invite à l'essayer gratuitement pendant 2 jours, sans engagement :\n{trial}\n\n"
            "Je reste à votre disposition pour en parler quand vous le souhaitez, il suffit de répondre à cet e-mail.\n\n"
            f"Bien cordialement,\nL'équipe {sender_org}\n\n"
            f"—\nVous recevez ce message car {company or 'votre entreprise'} correspond au profil de nos clients professionnels. "
            f"Pour ne plus recevoir nos messages : {unsub}")
    return {"prospect_id": prospect_id, "contact": contact, "contacts": contacts, "to": contact["email"] if contact else None,
            "subject": subject, "body": body, "method": method, "trial_url": trial, "unsubscribe_url": unsub}


def send(prospect_id: str, mailbox_id: str, to: str, subject: str, body: str) -> dict:
    """Sends ONE reviewed e-mail (or a follow-up in the same thread) and records it in the prospect history."""
    from apps.email_center.services import send_email
    tid = get_context().tenant_id
    c = fetch_one("""SELECT id, consent_status FROM public.prospect_contacts WHERE tenant_id = %s AND prospect_id = %s
                      AND lower(email) = lower(%s) AND deleted_at IS NULL""", [tid, prospect_id, to])
    if not c:
        raise BusinessError("Ce destinataire n'est pas un contact de ce prospect", "unknown_recipient")
    if c[1] == "opted_out":
        raise BusinessError("Ce contact s'est désinscrit", "recipient_suppressed", status_code=409)
    if "/public/prospects/unsubscribe/" not in body:
        raise BusinessError("Le lien de désinscription doit rester dans l'e-mail", "unsubscribe_link_required")
    conv = fetch_one("""SELECT id FROM public.email_conversations WHERE tenant_id = %s AND prospect_id = %s
                         ORDER BY last_message_at DESC NULLS LAST LIMIT 1""", [tid, prospect_id])
    mid = send_email(mailbox_id, [to], subject, body, conversation_id=str(conv[0]) if conv else None, prospect_id=prospect_id)
    fetch_one("""UPDATE public.prospects SET status = CASE WHEN status IN ('new','new_lead','enriched','qualified') THEN 'contacted' ELSE status END
                  WHERE id = %s RETURNING 1""", [prospect_id])
    return {"message_id": mid, "follow_up": bool(conv)}


def history(prospect_id: str) -> dict:
    """Per-prospect follow-up: e-mails sent (when), replies, trial-link clicks / contact requests, unsubscribes."""
    tid = get_context().tenant_id
    emails = fetch_all_dict("""SELECT id, direction, subject, status, classification, coalesce(received_at, sent_at, created_at) AS at, from_email, to_emails
                                 FROM public.email_messages WHERE tenant_id = %s AND prospect_id = %s ORDER BY 6 DESC LIMIT 200""", [tid, prospect_id])
    events = fetch_all_dict("""SELECT activity_type, summary, created_at AS at, entity_ref FROM public.crm_activities
                                WHERE tenant_id = %s AND prospect_id = %s ORDER BY created_at DESC LIMIT 200""", [tid, prospect_id])
    sent = [e for e in emails if e["direction"] == "outbound" and e["status"] not in ("failed", "draft")]
    replies = [e for e in emails if e["direction"] == "inbound"]
    clicks = [e for e in events if (e.get("entity_ref") or {}).get("event") == "trial_link_clicked"]
    return {"emails": emails, "events": events, "summary": {
        "sent": len(sent), "last_sent_at": sent[0]["at"] if sent else None, "replied": bool(replies),
        "last_reply_at": replies[0]["at"] if replies else None, "trial_clicks": len(clicks),
        "contact_request": bool(clicks) or any(r.get("classification") in ("demo_requested", "interested", "information_request") for r in replies)}}
