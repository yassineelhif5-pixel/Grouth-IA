"""Visibility analyzer — pure functions over real HTTP observations (no invented data).

- technical_checks(): robots.txt, AI crawlers, sitemaps, canonical, HTTPS, 404, 301, hreflang, Open Graph, JSON-LD, llms.txt
- extract_keywords(): weighted n-grams from titles, headings, meta descriptions and page text actually downloaded
- keyword_gap(): competitor keywords absent from the site
- generate_assets(): robots.txt, sitemap.xml, sitemap-images.xml, JSON-LD, Open Graph, hreflang, 404 page, redirects, llms.txt
"""
from __future__ import annotations

import json
import re
import secrets
from collections import Counter
from datetime import UTC, datetime
from html import escape as _html_escape
from urllib import robotparser
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


def escape(text: str, entities: dict[str, str] | None = None) -> str:
    """XML/HTML text escaping (&, <, >, plus optional extra entities) for generated files — no XML is ever parsed here."""
    out = _html_escape(str(text), quote=False)
    for k, v in (entities or {}).items():
        out = out.replace(k, v)
    return out


AI_CRAWLERS = ["GPTBot", "OAI-SearchBot", "ChatGPT-User", "ClaudeBot", "Claude-Web", "PerplexityBot", "Google-Extended",
               "Applebot-Extended", "Bingbot", "Googlebot", "CCBot"]

STOPWORDS = set("""
a à au aux avec ce ces cet cette dans de des du elle en et eux il ils je la le les leur lui ma mais me même mes moi mon ne nos notre
nous on ou où par pas pour qu que qui sa se ses son sur ta te tes toi ton tu un une vos votre vous c d j l m n s t y été être avoir
est sont plus moins très tout tous toute toutes comme si leurs ainsi aussi faire fait peut sans entre chez vers dont depuis cela ça
the a an and or of to in on for with by from at is are be as it this that these those your our you we they their its into about
not no can will just more most all any how what why when where who which use using get new one two three page home accueil
menu contact login sign up cookies cookie politique privacy policy mentions légales copyright rights reserved inc ltd www http https com
""".split())

WORD_RE = re.compile(r"[a-zA-ZÀ-ÖØ-öø-ÿ0-9][a-zA-ZÀ-ÖØ-öø-ÿ0-9'’\-]{1,}")


def _tokens(text: str) -> list[str]:
    return [w.lower().strip("'’-") for w in WORD_RE.findall(text or "")]


def extract_keywords(docs: list[tuple[str, float]], top: int = 40) -> list[dict]:
    """docs = [(text, weight)] → [{keyword, score, occurrences, ngram}] — 1 to 3-word terms without stop words at the edges."""
    scores: Counter = Counter()
    counts: Counter = Counter()
    for text, weight in docs:
        toks = _tokens(text)
        for n in (1, 2, 3):
            for i in range(len(toks) - n + 1):
                gram = toks[i:i + n]
                if gram[0] in STOPWORDS or gram[-1] in STOPWORDS or any(len(g) < 3 for g in (gram[0], gram[-1])):
                    continue
                if gram[0].isdigit():
                    continue
                term = " ".join(gram)
                scores[term] += weight * (1 + 0.6 * (n - 1))
                counts[term] += 1
    # drop single words fully covered by a stronger multi-word term
    out = []
    for term, sc in scores.most_common(top * 4):
        if counts[term] < 2 and " " not in term:
            continue
        out.append({"keyword": term, "score": round(sc, 2), "occurrences": counts[term], "ngram": term.count(" ") + 1})
        if len(out) >= top:
            break
    return out


def keyword_gap(site: list[dict], competitors: dict[str, list[dict]], top: int = 25) -> list[dict]:
    mine = {k["keyword"] for k in site}
    mine_words = {w for k in mine for w in k.split()}
    agg: dict[str, dict] = {}
    for comp, kws in competitors.items():
        for k in kws:
            term = k["keyword"]
            if term in mine or (k["ngram"] == 1 and term in mine_words):
                continue
            a = agg.setdefault(term, {"keyword": term, "competitors": [], "score": 0.0})
            a["competitors"].append(comp)
            a["score"] += k["score"]
    ranked = sorted(agg.values(), key=lambda a: (len(a["competitors"]), a["score"]), reverse=True)
    return ranked[:top]


def page_documents(pages: list[dict], home_text: str = "") -> list[tuple[str, float]]:
    docs: list[tuple[str, float]] = []
    for p in pages:
        if p.get("title"):
            docs.append((p["title"], 3.0))
        if p.get("meta_description"):
            docs.append((p["meta_description"], 2.0))
        for lvl, text in p.get("headings") or []:
            docs.append((text, 2.5 if lvl == "h1" else 1.5 if lvl in ("h2", "h3") else 1.0))
    if home_text:
        docs.append((home_text[:20000], 0.4))
    return docs


# ─────────────────────────── technical checks ───────────────────────────
def _get(session: requests.Session, url: str, **kw) -> requests.Response | None:
    try:
        return session.get(url, timeout=kw.pop("timeout", 15), **kw)
    except requests.RequestException:
        return None


def inspect_home(html: str, base_url: str) -> dict:
    soup = BeautifulSoup(html or "", "html.parser")
    hreflang = [{"lang": link.get("hreflang"), "href": urljoin(base_url, link.get("href", ""))}
                for link in soup.find_all("link", rel=lambda v: v and "alternate" in v) if link.get("hreflang")]
    og = {m["property"]: (m.get("content") or "")[:300] for m in soup.find_all("meta", property=re.compile("^og:")) if m.get("property")}
    twitter = {m["name"]: (m.get("content") or "")[:300] for m in soup.find_all("meta", attrs={"name": re.compile("^twitter:")})}
    jsonld, invalid = [], 0
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(s.string or "")
            items = data if isinstance(data, list) else data.get("@graph", [data])
            jsonld += [i for i in items if isinstance(i, dict)]
        except (json.JSONDecodeError, AttributeError):
            invalid += 1
    can = soup.find("link", rel=lambda v: v and "canonical" in v)
    title = soup.title.string.strip() if soup.title and soup.title.string else None
    md = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
    for t in soup(["script", "style", "noscript", "svg"]):
        t.decompose()
    text = soup.get_text(" ", strip=True)
    return {"hreflang": hreflang, "open_graph": og, "twitter": twitter,
            "jsonld_types": sorted({str(i.get("@type")) for i in jsonld if i.get("@type")}), "jsonld_invalid": invalid,
            "canonical": urljoin(base_url, can["href"]) if can and can.get("href") else None, "title": title,
            "meta_description": (md.get("content") or "").strip() if md else None, "text": text[:30000],
            "lang": soup.html.get("lang") if soup.html else None}


def technical_checks(site_url: str, user_agent: str, session: requests.Session | None = None) -> dict:
    """Observes the site and returns {checks: [{code, label, status: ok|warning|error|info, detail, evidence}], home: {...}}."""
    s = session or requests.Session()
    s.headers.setdefault("User-Agent", user_agent)
    start = site_url if "://" in site_url else f"https://{site_url}"
    p = urlparse(start)
    host = p.netloc
    root = f"https://{host}"
    checks: list[dict] = []

    def add(code, label, status, detail, evidence=None):
        checks.append({"code": code, "label": label, "status": status, "detail": detail, "evidence": evidence or {}})

    home = _get(s, root + "/") if p.scheme != "http" else None
    if home is None:
        root = f"http://{host}"
        home = _get(s, root + "/")
    reachable = home is not None and home.status_code < 500
    add("reachable", "Site accessible", "ok" if reachable else "error",
        f"HTTP {home.status_code}" if home is not None else "Site injoignable", {"url": root})
    if not reachable:
        return {"root": root, "host": host, "checks": checks, "home": {}}

    # HTTPS + 301
    http_r = _get(s, f"http://{host}/", allow_redirects=False)
    https_ok = home.url.startswith("https://")
    if http_r is not None and http_r.status_code in (301, 308) and http_r.headers.get("Location", "").startswith("https://"):
        add("https", "HTTPS obligatoire", "ok", "HTTP redirige en permanence (301) vers HTTPS", {"location": http_r.headers.get("Location")})
    elif https_ok:
        st = http_r.status_code if http_r is not None else None
        add("https", "HTTPS obligatoire", "warning", f"HTTPS disponible mais HTTP ne redirige pas en 301 (statut {st})", {"http_status": st})
    else:
        add("https", "HTTPS obligatoire", "error", "Le site n'est pas servi en HTTPS", {})
    alt_host = host[4:] if host.startswith("www.") else f"www.{host}"
    alt = _get(s, f"https://{alt_host}/", allow_redirects=False) if "." in host.split(":")[0] and not host[0].isdigit() else None
    if alt is not None:
        if alt.status_code in (301, 308):
            add("redirect_301", "Redirections permanentes (301)", "ok", f"{alt_host} redirige en 301 vers la version principale",
                {"location": alt.headers.get("Location")})
        elif alt.status_code == 200:
            add("redirect_301", "Redirections permanentes (301)", "warning",
                f"{alt_host} et {host} répondent tous les deux : contenu dupliqué, ajouter une redirection 301", {"status": alt.status_code})
        else:
            add("redirect_301", "Redirections permanentes (301)", "info", f"{alt_host} répond {alt.status_code}", {})
    else:
        add("redirect_301", "Redirections permanentes (301)", "info", f"{alt_host} n'est pas configuré", {})

    # robots.txt + AI crawlers
    rob = _get(s, root + "/robots.txt")
    robots_txt = rob.text if rob is not None and rob.status_code == 200 and "html" not in rob.headers.get("Content-Type", "") else None
    if robots_txt is None:
        add("robots_txt", "robots.txt", "error", "Aucun robots.txt : les robots n'ont ni règles ni lien vers le sitemap", {})
        allowed = {c: True for c in AI_CRAWLERS}
    else:
        rp = robotparser.RobotFileParser()
        rp.parse(robots_txt.splitlines())
        allowed = {c: rp.can_fetch(c, root + "/") for c in AI_CRAWLERS}
        has_sitemap = "sitemap:" in robots_txt.lower()
        add("robots_txt", "robots.txt", "ok" if has_sitemap else "warning",
            "robots.txt présent" + ("" if has_sitemap else " mais sans directive Sitemap"), {"size": len(robots_txt)})
    blocked = [c for c, ok in allowed.items() if not ok]
    add("ai_crawlers", "Crawlers souhaités autorisés (moteurs + IA)", "ok" if not blocked else "warning",
        "Tous les crawlers suivis sont autorisés" if not blocked else f"Bloqués : {', '.join(blocked)}", {"allowed": allowed})

    # sitemaps
    sm_urls: list[str] = []
    candidates = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", robots_txt or "") or [root + "/sitemap.xml", root + "/sitemap_index.xml"]
    sm_found, has_images, has_news, sm_count = None, False, False, 0
    for c in candidates[:5]:
        r = _get(s, c)
        if r is not None and r.status_code == 200 and "<" in r.text[:200]:
            sm_found = c
            body = r.text
            has_images = has_images or "image:image" in body or "sitemap-images" in body or "image-sitemap" in body
            has_news = has_news or "news:news" in body or "sitemap-news" in body
            locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", body)
            for loc in locs[:20]:
                if loc.endswith(".xml"):
                    sub = _get(s, loc)
                    if sub is not None and sub.status_code == 200:
                        has_images = has_images or "image:image" in sub.text
                        has_news = has_news or "news:news" in sub.text
                        sm_urls += re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", sub.text)
                else:
                    sm_urls.append(loc)
            break
    sm_count = len(set(sm_urls))
    add("sitemap_xml", "sitemap.xml", "ok" if sm_found else "error",
        f"{sm_count} URL déclarées dans {sm_found}" if sm_found else "Aucun sitemap.xml trouvé", {"url": sm_found, "urls": sm_count})
    add("sitemap_images", "sitemap-images.xml", "ok" if has_images else "info",
        "Images déclarées dans le sitemap" if has_images else "Pas de sitemap d'images (utile si le site contient des visuels importants)", {})
    add("sitemap_news", "sitemap-news.xml", "ok" if has_news else "info",
        "Sitemap news présent" if has_news else "Pas de sitemap news (uniquement pour un contenu éditorial éligible à Google News)", {})

    info = inspect_home(home.text if "html" in home.headers.get("Content-Type", "") else "", home.url)
    add("canonical", "Balise canonical", "ok" if info["canonical"] else "warning",
        f"Canonical : {info['canonical']}" if info["canonical"] else "Pas de canonical sur la page d'accueil (risque d'URL dupliquées)", {})
    add("hreflang", "hreflang (multilingue)", "ok" if info["hreflang"] else "info",
        f"{len(info['hreflang'])} versions linguistiques déclarées" if info["hreflang"] else "Aucune balise hreflang (nécessaire si le site existe en plusieurs langues)",
        {"hreflang": info["hreflang"][:20]})
    og_needed = {"og:title", "og:description", "og:image", "og:url", "og:type"}
    og_missing = sorted(og_needed - set(info["open_graph"]))
    add("open_graph", "Open Graph (partage social)", "ok" if not og_missing else "warning" if info["open_graph"] else "error",
        "Balises Open Graph complètes" if not og_missing else f"Manquantes : {', '.join(og_missing)}", {"present": info["open_graph"]})
    want = {"Organization", "WebSite", "SoftwareApplication", "Product", "FAQPage", "BreadcrumbList"}
    have = set(info["jsonld_types"])
    add("json_ld", "Données structurées JSON-LD", "ok" if have & {"Organization", "SoftwareApplication", "Product"} else "warning" if have else "error",
        f"Types présents : {', '.join(sorted(have))}" if have else "Aucune donnée structurée JSON-LD",
        {"present": sorted(have), "suggested": sorted(want - have), "invalid": info["jsonld_invalid"]})

    # 404
    probe = f"{root}/growth-ia-404-check-{secrets.token_hex(4)}"
    nf = _get(s, probe)
    if nf is None:
        add("page_404", "Page 404 personnalisée", "info", "Test impossible", {})
    elif nf.status_code == 404:
        words = len(BeautifulSoup(nf.text, "html.parser").get_text(" ", strip=True).split()) if "html" in nf.headers.get("Content-Type", "") else 0
        add("page_404", "Page 404 personnalisée", "ok" if words > 25 else "warning",
            "Statut 404 correct" + (" avec une page personnalisée" if words > 25 else " mais page très pauvre (proposer navigation et recherche)"),
            {"status": 404, "words": words})
    else:
        add("page_404", "Page 404 personnalisée", "error", f"Une page inexistante répond {nf.status_code} (soft 404 : à corriger)",
            {"status": nf.status_code})

    llms = _get(s, root + "/llms.txt")
    has_llms = llms is not None and llms.status_code == 200 and "html" not in llms.headers.get("Content-Type", "")
    add("llms_txt", "llms.txt (moteurs IA)", "ok" if has_llms else "info",
        "llms.txt présent" if has_llms else "Pas de llms.txt : fichier recommandé pour guider les moteurs IA vers les pages clés", {})
    add("title_meta", "Titre et méta-description", "ok" if info["title"] and info["meta_description"] else "warning",
        f"Titre : {info['title'] or '—'} · Description : {(info['meta_description'] or '—')[:120]}", {})

    return {"root": root, "host": host, "checks": checks, "home": info, "sitemap_urls": sorted(set(sm_urls))[:5000],
            "robots_txt": (robots_txt or "")[:5000], "allowed_crawlers": allowed}


def score_checks(checks: list[dict]) -> int:
    weight = {"ok": 1.0, "info": 0.8, "warning": 0.5, "error": 0.0}
    rel = [weight.get(c["status"], 0.5) for c in checks if c["code"] != "reachable"]
    return round(100 * sum(rel) / len(rel)) if rel else 0


# ─────────────────────────── generated assets ───────────────────────────
def gen_robots(root: str, sitemap_url: str | None) -> str:
    lines = ["# robots.txt généré par Growth IA — à relire avant mise en ligne", "User-agent: *", "Allow: /",
             "Disallow: /admin/", "Disallow: /api/", ""]
    for bot in ["GPTBot", "OAI-SearchBot", "ClaudeBot", "PerplexityBot", "Google-Extended", "Applebot-Extended"]:
        lines += [f"User-agent: {bot}", "Allow: /", ""]
    lines.append(f"Sitemap: {sitemap_url or root + '/sitemap.xml'}")
    return "\n".join(lines) + "\n"


def gen_sitemap(urls: list[str]) -> str:
    today = datetime.now(UTC).date().isoformat()
    body = "\n".join(f"  <url><loc>{escape(u)}</loc><lastmod>{today}</lastmod></url>" for u in sorted(set(urls))[:50000])
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{body}\n</urlset>\n'


def gen_sitemap_images(pages: list[dict]) -> str:
    rows = []
    for p in pages:
        imgs = p.get("image_urls") or []
        if imgs:
            imgx = "".join(f"<image:image><image:loc>{escape(i)}</image:loc></image:image>" for i in imgs[:50])
            rows.append(f"  <url><loc>{escape(p['url'])}</loc>{imgx}</url>")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
            'xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">\n' + "\n".join(rows) + "\n</urlset>\n")


def gen_jsonld(name: str, root: str, description: str, logo: str | None, same_as: list[str], faq: list[tuple[str, str]]) -> str:
    graph = [
        {"@type": "Organization", "@id": f"{root}/#org", "name": name, "url": root, **({"logo": logo} if logo else {}),
         **({"sameAs": same_as} if same_as else {})},
        {"@type": "WebSite", "@id": f"{root}/#website", "url": root, "name": name, "publisher": {"@id": f"{root}/#org"}},
        {"@type": "SoftwareApplication", "name": name, "url": root, "applicationCategory": "BusinessApplication",
         "operatingSystem": "Web", "description": description[:300], "publisher": {"@id": f"{root}/#org"}},
    ]
    if faq:
        graph.append({"@type": "FAQPage", "mainEntity": [{"@type": "Question", "name": q,
                                                          "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in faq[:10]]})
    return '<script type="application/ld+json">\n' + json.dumps({"@context": "https://schema.org", "@graph": graph},
                                                                ensure_ascii=False, indent=2) + "\n</script>\n"


def gen_open_graph(name: str, root: str, title: str, description: str, image: str | None) -> str:
    tags = [("og:type", "website"), ("og:site_name", name), ("og:url", root + "/"), ("og:title", title),
            ("og:description", description[:200]), ("og:image", image or f"{root}/og-image.png")]
    out = [f'<meta property="{k}" content="{escape(v, {chr(34): "&quot;"})}">' for k, v in tags]
    out += ['<meta name="twitter:card" content="summary_large_image">',
            f'<meta name="twitter:title" content="{escape(title, {chr(34): "&quot;"})}">',
            f'<meta name="twitter:description" content="{escape(description[:200], {chr(34): "&quot;"})}">']
    return "\n".join(out) + "\n"


def gen_hreflang(root: str, languages: list[str]) -> str:
    langs = languages or ["fr"]
    out = [f'<link rel="alternate" hreflang="{lang}" href="{root}/{lang}/">' for lang in langs]
    out.append(f'<link rel="alternate" hreflang="x-default" href="{root}/">')
    return "\n".join(out) + "\n"


def gen_canonical(root: str) -> str:
    return (f'<!-- Sur chaque page, pointer vers l\'URL de référence (sans paramètres, en HTTPS) -->\n'
            f'<link rel="canonical" href="{root}/">\n')


def gen_404(name: str, root: str) -> str:
    return f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>Page introuvable — {escape(name)}</title>
<style>body{{font-family:system-ui,sans-serif;background:#0b1020;color:#e6e9f2;display:grid;place-items:center;min-height:100vh;margin:0}}
main{{max-width:560px;padding:32px;text-align:center}}a{{color:#7aa2ff}}h1{{font-size:56px;margin:0}}</style></head>
<body><main><h1>404</h1><p>Cette page n'existe pas ou a été déplacée.</p>
<p><a href="{root}/">Retour à l'accueil</a> · <a href="{root}/blog/">Blog</a> · <a href="{root}/contact/">Contact</a></p>
</main></body></html>
"""


def gen_redirects(host: str) -> str:
    bare = host[4:] if host.startswith("www.") else host
    return (f"# Redirections 301 (exemples Nginx) — version principale : https://{host}\n"
            f"server {{ listen 80; server_name {bare} www.{bare}; return 301 https://{host}$request_uri; }}\n"
            f"server {{ listen 443 ssl; server_name {'www.' + bare if not host.startswith('www.') else bare}; return 301 https://{host}$request_uri; }}\n"
            "# Netlify/Vercel : utiliser le fichier de redirections de la plateforme avec un statut 301.\n")


def gen_llms_txt(name: str, root: str, description: str, key_pages: list[tuple[str, str]]) -> str:
    lines = [f"# {name}", "", f"> {description[:300]}", "", "## Pages clés"]
    lines += [f"- [{t or u}]({u})" for u, t in key_pages[:30]]
    return "\n".join(lines) + "\n"
