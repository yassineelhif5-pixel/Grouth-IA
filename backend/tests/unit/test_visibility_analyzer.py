"""Visibility analyzer against a real local HTTP site: every finding comes from an actual HTTP response."""
import http.server
import threading

import pytest

from apps.visibility import analyzer

HOME = ('<html lang="fr"><head><title>Acme CRM — logiciel CRM pour PME</title>'
        '<meta name="description" content="Acme CRM, le logiciel CRM simple pour les PME : pipeline commercial, relances automatiques.">'
        '<meta property="og:title" content="Acme CRM"><link rel="alternate" hreflang="en" href="/en/">'
        '<script type="application/ld+json">{"@context":"https://schema.org","@type":"Organization","name":"Acme"}</script></head>'
        '<body><h1>Logiciel CRM pour PME</h1><h2>Pipeline commercial</h2><h2>Relances automatiques</h2><a href="/comparatif-crm">Comparatif</a>'
        + "<p>Le logiciel CRM Acme aide les PME à gérer leur pipeline commercial et leurs relances automatiques.</p>" * 20
        + "</body></html>")
SITE = {
    "/": ("text/html", HOME),
    "/comparatif-crm": ("text/html", '<html><body><h1>Acme, une alternative à Pipedrive</h1>'
                        '<p>Acme vs HubSpot : comparé à Salesforce, Acme est plus simple.</p>'
                        '<a href="https://www.pipedrive.com/fr">Pipedrive</a><a href="https://twitter.com/acme">Twitter</a></body></html>'),
    "/robots.txt": ("text/plain", "User-agent: *\nAllow: /\nUser-agent: GPTBot\nDisallow: /\n"),
}


@pytest.fixture(scope="module")
def site():
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path not in SITE:
                self.send_response(404)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(b"<html><body>Not found</body></html>")
                return
            ctype, body = SITE[self.path]
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.end_headers()
            self.wfile.write(body.encode())

        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_technical_checks_observe_the_site(site):
    res = analyzer.technical_checks(site + "/", "GrowthIA-Test")
    c = {x["code"]: x for x in res["checks"]}
    assert c["reachable"]["status"] == "ok"
    assert c["https"]["status"] == "error"                       # served over plain HTTP
    assert c["robots_txt"]["status"] == "warning"                # present but no Sitemap directive
    assert c["ai_crawlers"]["status"] == "warning" and "GPTBot" in c["ai_crawlers"]["detail"]
    assert c["sitemap_xml"]["status"] == "error"
    assert c["canonical"]["status"] == "warning"
    assert c["hreflang"]["status"] == "ok"
    assert c["open_graph"]["status"] == "warning" and "og:image" in c["open_graph"]["detail"]
    assert c["json_ld"]["status"] == "ok" and "Organization" in c["json_ld"]["evidence"]["present"]
    assert c["page_404"]["status"] == "warning"                  # real 404 status but an empty page
    assert c["llms_txt"]["status"] == "info"
    assert 0 < analyzer.score_checks(res["checks"]) < 100


def test_keywords_and_gap_are_extracted_from_real_text(site):
    res = analyzer.technical_checks(site + "/", "GrowthIA-Test")
    pages = [{"title": res["home"]["title"], "meta_description": res["home"]["meta_description"],
              "headings": [("h1", "Logiciel CRM pour PME"), ("h2", "Pipeline commercial")]}]
    kws = analyzer.extract_keywords(analyzer.page_documents(pages, res["home"]["text"]))
    terms = [k["keyword"] for k in kws]
    assert "logiciel crm" in terms and "pipeline commercial" in terms
    gap = analyzer.keyword_gap(kws, {"Rival": [{"keyword": "facturation en ligne", "score": 9, "ngram": 2, "occurrences": 4},
                                               {"keyword": "logiciel crm", "score": 9, "ngram": 2, "occurrences": 4}]})
    assert [g["keyword"] for g in gap] == ["facturation en ligne"]


def test_generated_assets_are_valid():
    assert "Sitemap: https://acme.fr/sitemap.xml" in analyzer.gen_robots("https://acme.fr", None)
    sm = analyzer.gen_sitemap(["https://acme.fr/", "https://acme.fr/a&b"])
    assert "<loc>https://acme.fr/a&amp;b</loc>" in sm and sm.startswith("<?xml")
    ld = analyzer.gen_jsonld("Acme", "https://acme.fr", "CRM", None, [], [("Q?", "R.")])
    assert '"FAQPage"' in ld and '"SoftwareApplication"' in ld
    assert 'hreflang="x-default"' in analyzer.gen_hreflang("https://acme.fr", ["fr", "en"])
    assert "noindex" in analyzer.gen_404("Acme", "https://acme.fr")
    assert analyzer.gen_llms_txt("Acme", "https://acme.fr", "CRM", [("https://acme.fr/", "Accueil")]).startswith("# Acme")


def test_competitor_mentions_are_observed_with_evidence(site):
    found = analyzer.find_competitor_mentions(site, "GrowthIA-Test/1.0")
    names = {f["name"] for f in found}
    assert {"Pipedrive", "HubSpot", "Salesforce"} <= names
    assert all(f["source"] == "site_mentions" and f["evidence"] for f in found)
    pd = next(f for f in found if f["name"] == "Pipedrive")
    assert pd["url"] == "https://pipedrive.com" and pd["mentions"] >= 2
    assert not any("twitter" in (f["url"] or "") for f in found)  # social links are ignored
