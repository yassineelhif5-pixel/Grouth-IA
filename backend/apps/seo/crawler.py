"""Polite SEO crawler + analyzers (pure Python, no Django import → unit-testable).

Respects robots.txt (user-agent specific rules and Crawl-delay), stays on the audited host, bounded pages,
HTML only, timeouts. Every finding is derived from what was actually fetched — nothing is estimated.
"""
from __future__ import annotations

import json
import re
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, field
from urllib import robotparser
from urllib.parse import urldefrag, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

SEVERITY_WEIGHT = {"critical": 10, "high": 6, "medium": 3, "low": 1, "info": 0}


@dataclass
class PageResult:
    url: str
    status_code: int | None
    load_ms: int | None
    content_type: str = ""
    title: str | None = None
    meta_description: str | None = None
    canonical: str | None = None
    noindex: bool = False
    lang: str | None = None
    h1: list[str] = field(default_factory=list)
    headings: list[tuple[str, str]] = field(default_factory=list)
    word_count: int = 0
    images: int = 0
    images_without_alt: int = 0
    internal_links: set[str] = field(default_factory=set)
    external_links: set[str] = field(default_factory=set)
    schema_types: list[str] = field(default_factory=list)
    has_viewport: bool = False
    og_tags: dict = field(default_factory=dict)
    redirected_to: str | None = None
    error: str | None = None

    def as_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k not in ("internal_links", "external_links", "headings")}
        d["internal_links"] = len(self.internal_links)
        d["external_links"] = len(self.external_links)
        d["headings"] = self.headings[:50]
        return d


@dataclass
class Issue:
    code: str
    severity: str
    category: str
    description: str
    page_url: str | None = None
    impact: str = "medium"
    details: dict = field(default_factory=dict)


@dataclass
class CrawlResult:
    root: str
    pages: list[PageResult]
    robots_txt: str | None
    robots_allowed: bool
    sitemap_urls: list[str]
    blocked_by_robots: list[str]
    issues: list[Issue] = field(default_factory=list)
    score: float = 0.0
    duration_ms: int = 0


def normalize(url: str) -> str:
    url, _ = urldefrag(url)
    p = urlparse(url)
    path = p.path or "/"
    return f"{p.scheme}://{p.netloc.lower()}{path}" + (f"?{p.query}" if p.query else "")


class Crawler:
    def __init__(self, user_agent: str, max_pages: int = 50, delay: float = 0.5, timeout: float = 15, session=None):
        self.ua, self.max_pages, self.delay, self.timeout = user_agent, max_pages, delay, timeout
        self.s = session or requests.Session()
        self.s.headers.update({"User-Agent": user_agent, "Accept": "text/html,application/xhtml+xml"})

    def _robots(self, root: str) -> tuple[robotparser.RobotFileParser, str | None]:
        rp = robotparser.RobotFileParser()
        try:
            r = self.s.get(urljoin(root, "/robots.txt"), timeout=self.timeout)
            text = r.text if r.status_code == 200 else None
        except requests.RequestException:
            text = None
        rp.parse((text or "").splitlines())
        return rp, text

    def _sitemaps(self, root: str, robots_txt: str | None) -> list[str]:
        candidates = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", robots_txt or "") or [urljoin(root, "/sitemap.xml")]
        urls: list[str] = []
        for sm in candidates[:5]:
            try:
                r = self.s.get(sm, timeout=self.timeout)
                if r.status_code != 200:
                    continue
                tree = ET.fromstring(r.content)
                locs = [e.text.strip() for e in tree.iter() if e.tag.endswith("loc") and e.text]
                if tree.tag.endswith("sitemapindex"):
                    for child in locs[:5]:
                        c = self.s.get(child, timeout=self.timeout)
                        if c.status_code == 200:
                            urls += [e.text.strip() for e in ET.fromstring(c.content).iter() if e.tag.endswith("loc") and e.text]
                else:
                    urls += locs
            except (requests.RequestException, ET.ParseError):
                continue
        return [normalize(u) for u in urls[:5000]]

    def fetch(self, url: str, host: str) -> PageResult:
        t0 = time.monotonic()
        try:
            r = self.s.get(url, timeout=self.timeout, allow_redirects=True)
        except requests.RequestException as e:
            return PageResult(url, None, None, error=type(e).__name__)
        pr = PageResult(url, r.status_code, int((time.monotonic() - t0) * 1000), r.headers.get("Content-Type", ""))
        if normalize(r.url) != normalize(url):
            pr.redirected_to = normalize(r.url)
        if "html" not in pr.content_type or r.status_code >= 400:
            return pr
        soup = BeautifulSoup(r.text, "html.parser")
        pr.title = (soup.title.string or "").strip() if soup.title and soup.title.string else None
        md = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
        pr.meta_description = (md.get("content") or "").strip() if md else None
        can = soup.find("link", rel=lambda v: v and "canonical" in v)
        pr.canonical = urljoin(r.url, can["href"]) if can and can.get("href") else None
        rob = soup.find("meta", attrs={"name": re.compile("^robots$", re.I)})
        pr.noindex = bool(rob and "noindex" in (rob.get("content") or "").lower()) or "noindex" in r.headers.get("X-Robots-Tag", "").lower()
        pr.lang = soup.html.get("lang") if soup.html else None
        pr.has_viewport = bool(soup.find("meta", attrs={"name": "viewport"}))
        for h in soup.find_all(re.compile("^h[1-6]$")):
            pr.headings.append((h.name, h.get_text(" ", strip=True)[:150]))
        pr.h1 = [t for n, t in pr.headings if n == "h1"]
        imgs = soup.find_all("img")
        pr.images, pr.images_without_alt = len(imgs), sum(1 for i in imgs if not (i.get("alt") or "").strip())
        for og in soup.find_all("meta", property=re.compile("^og:")):
            pr.og_tags[og["property"]] = (og.get("content") or "")[:200]
        for s in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(s.string or "")
                items = data if isinstance(data, list) else data.get("@graph", [data])
                pr.schema_types += [str(i.get("@type")) for i in items if isinstance(i, dict) and i.get("@type")]
            except (json.JSONDecodeError, AttributeError):
                pr.schema_types.append("invalid_json_ld")
        pr.schema_types += [t.rsplit("/", 1)[-1] for t in (e.get("itemtype") for e in soup.find_all(attrs={"itemtype": True})) if t]
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if href.startswith(("mailto:", "tel:", "javascript:", "#")):
                continue
            absu = normalize(urljoin(r.url, href))
            (pr.internal_links if urlparse(absu).netloc.lower() == host else pr.external_links).add(absu)
        for t in soup(["script", "style", "noscript"]):
            t.decompose()
        pr.word_count = len(soup.get_text(" ", strip=True).split())
        return pr

    def crawl(self, start_url: str) -> CrawlResult:
        t0 = time.monotonic()
        start = normalize(start_url if "://" in start_url else f"https://{start_url}")
        p = urlparse(start)
        root, host = f"{p.scheme}://{p.netloc}", p.netloc.lower()
        rp, robots_txt = self._robots(root)
        delay = max(self.delay, float(rp.crawl_delay(self.ua) or 0))
        sitemap = self._sitemaps(root, robots_txt)
        queue, seen, pages, blocked = [start] + [u for u in sitemap if urlparse(u).netloc.lower() == host], set(), [], []
        allowed_root = rp.can_fetch(self.ua, start)
        while queue and len(pages) < self.max_pages:
            url = queue.pop(0)
            if url in seen:
                continue
            seen.add(url)
            if not rp.can_fetch(self.ua, url):
                blocked.append(url)
                continue
            pr = self.fetch(url, host)
            pages.append(pr)
            for link in sorted(pr.internal_links):
                if link not in seen and len(seen) + len(queue) < self.max_pages * 5:
                    queue.append(link)
            if delay:
                time.sleep(delay)
        res = CrawlResult(root, pages, robots_txt, allowed_root, sitemap, blocked)
        res.issues = analyze(res)
        res.score = score(res)
        res.duration_ms = int((time.monotonic() - t0) * 1000)
        return res


def analyze(res: CrawlResult) -> list[Issue]:
    issues: list[Issue] = []
    add = issues.append
    if res.robots_txt is None:
        add(Issue("robots_missing", "low", "technical", "robots.txt is missing", res.root, "low"))
    if not res.robots_allowed:
        add(Issue("robots_blocks_home", "critical", "technical", "robots.txt blocks the home page for crawlers", res.root, "high"))
    if not res.sitemap_urls:
        add(Issue("sitemap_missing", "medium", "technical", "No XML sitemap found (robots.txt / /sitemap.xml)", res.root, "medium"))
    titles, descs = defaultdict(list), defaultdict(list)
    crawled = {p.url for p in res.pages}
    linked: set[str] = set()
    status = {p.url: p.status_code for p in res.pages}
    for p in res.pages:
        linked |= p.internal_links
        if p.error or p.status_code is None:
            add(Issue("fetch_error", "high", "technical", f"Page could not be fetched ({p.error})", p.url, "high"))
            continue
        if p.status_code >= 500:
            add(Issue("http_5xx", "critical", "technical", f"Server error {p.status_code}", p.url, "high"))
        elif p.status_code >= 400:
            add(Issue("http_4xx", "high", "technical", f"Broken page ({p.status_code})", p.url, "high"))
        if p.status_code >= 400 or "html" not in p.content_type:
            continue
        if p.load_ms and p.load_ms > 3000:
            add(Issue("slow_response", "medium", "performance", f"Slow server response ({p.load_ms} ms)", p.url, "medium", {"load_ms": p.load_ms}))
        if not p.title:
            add(Issue("title_missing", "high", "onpage", "Missing <title>", p.url, "high"))
        else:
            titles[p.title].append(p.url)
            if len(p.title) > 60:
                add(Issue("title_too_long", "low", "onpage", f"Title longer than 60 characters ({len(p.title)})", p.url, "low"))
            if len(p.title) < 15:
                add(Issue("title_too_short", "low", "onpage", "Title shorter than 15 characters", p.url, "low"))
        if not p.meta_description:
            add(Issue("meta_description_missing", "medium", "onpage", "Missing meta description", p.url, "medium"))
        else:
            descs[p.meta_description].append(p.url)
            if len(p.meta_description) > 160:
                add(Issue("meta_description_too_long", "low", "onpage", "Meta description longer than 160 characters", p.url, "low"))
        if len(p.h1) == 0:
            add(Issue("h1_missing", "medium", "onpage", "No H1 heading", p.url, "medium"))
        elif len(p.h1) > 1:
            add(Issue("h1_multiple", "low", "onpage", f"{len(p.h1)} H1 headings", p.url, "low"))
        if p.images_without_alt:
            add(Issue("img_alt_missing", "low", "onpage", f"{p.images_without_alt}/{p.images} images without ALT", p.url, "low",
                      {"count": p.images_without_alt}))
        if not p.canonical:
            add(Issue("canonical_missing", "low", "technical", "No canonical link", p.url, "low"))
        elif normalize(p.canonical) != p.url and normalize(p.canonical) not in crawled:
            add(Issue("canonical_other", "info", "technical", f"Canonical points to {p.canonical}", p.url, "low"))
        if p.noindex:
            add(Issue("noindex", "high", "indexability", "Page excluded from indexing (noindex)", p.url, "high"))
        if not p.has_viewport:
            add(Issue("viewport_missing", "medium", "mobile", "No responsive viewport meta tag", p.url, "medium"))
        if not p.lang:
            add(Issue("lang_missing", "low", "onpage", "No lang attribute on <html>", p.url, "low"))
        if not p.schema_types:
            add(Issue("schema_missing", "low", "structured_data", "No Schema.org structured data", p.url, "medium"))
        elif "invalid_json_ld" in p.schema_types:
            add(Issue("schema_invalid", "medium", "structured_data", "Invalid JSON-LD block", p.url, "medium"))
        if p.word_count < 250:
            add(Issue("thin_content", "medium", "content", f"Thin content ({p.word_count} words)", p.url, "medium", {"words": p.word_count}))
        for link in p.internal_links:
            if status.get(link) and status[link] >= 400:
                add(Issue("broken_internal_link", "high", "links", f"Link to broken page {link}", p.url, "high", {"target": link}))
    for t, urls in titles.items():
        if len(urls) > 1:
            add(Issue("title_duplicate", "medium", "onpage", f"Title shared by {len(urls)} pages", urls[0], "medium", {"pages": urls[:20]}))
    for d, urls in descs.items():
        if len(urls) > 1:
            add(Issue("meta_description_duplicate", "low", "onpage", f"Meta description shared by {len(urls)} pages", urls[0], "low",
                      {"pages": urls[:20]}))
    for u in res.sitemap_urls:
        if u in crawled and u not in linked and u != normalize(res.root + "/"):
            add(Issue("orphan_page", "medium", "structure", "Page in sitemap but not linked internally", u, "medium"))
    return issues


def score(res: CrawlResult) -> float:
    ok_pages = max(1, sum(1 for p in res.pages if p.status_code and p.status_code < 400))
    penalty = sum(SEVERITY_WEIGHT[i.severity] for i in res.issues)
    return round(max(0.0, 100.0 - penalty * 10.0 / ok_pages), 1)


RECOMMENDATIONS = {
    "robots_blocks_home": ("Autoriser l'exploration de la page d'accueil", "Retirer la règle Disallow bloquante du robots.txt.", 1, "high", "low"),
    "sitemap_missing": ("Publier un sitemap XML", "Générer /sitemap.xml et le déclarer dans robots.txt et Search Console.", 2, "medium", "low"),
    "http_5xx": ("Corriger les erreurs serveur", "Analyser les logs serveur des URLs en erreur 5xx.", 1, "high", "medium"),
    "http_4xx": ("Corriger ou rediriger les pages cassées", "Restaurer la page ou ajouter une redirection 301.", 1, "high", "low"),
    "broken_internal_link": ("Réparer les liens internes cassés", "Mettre à jour les liens vers des URLs valides.", 1, "high", "low"),
    "title_missing": ("Ajouter des balises title", "Chaque page indexable doit avoir un titre unique et descriptif.", 1, "high", "low"),
    "title_duplicate": ("Rendre les titres uniques", "Différencier les titres des pages concernées.", 2, "medium", "low"),
    "meta_description_missing": ("Rédiger les meta descriptions", "150–160 caractères incitatifs par page.", 2, "medium", "low"),
    "h1_missing": ("Ajouter un H1 par page", "Un titre H1 clair reprenant l'intention principale.", 2, "medium", "low"),
    "noindex": ("Vérifier les pages en noindex", "Retirer noindex des pages qui doivent être indexées.", 1, "high", "low"),
    "viewport_missing": ("Rendre les pages responsive", "Ajouter <meta name=viewport> et vérifier le rendu mobile.", 2, "medium", "medium"),
    "schema_missing": ("Ajouter des données structurées", "Organization, Product/SoftwareApplication, FAQ, Article selon la page (utile aussi au GEO).", 3, "medium", "medium"),
    "schema_invalid": ("Corriger le JSON-LD", "Valider les blocs JSON-LD.", 2, "medium", "low"),
    "thin_content": ("Enrichir les contenus trop courts", "Développer les pages à faible contenu ou les fusionner.", 3, "medium", "medium"),
    "orphan_page": ("Relier les pages orphelines", "Ajouter des liens internes depuis des pages pertinentes.", 3, "medium", "low"),
    "img_alt_missing": ("Renseigner les attributs ALT", "Décrire les images informatives.", 4, "low", "low"),
    "slow_response": ("Améliorer le temps de réponse serveur", "Cache, CDN, optimisation backend.", 2, "medium", "high"),
    "canonical_missing": ("Déclarer des URLs canoniques", "Ajouter <link rel=canonical>.", 4, "low", "low"),
}
