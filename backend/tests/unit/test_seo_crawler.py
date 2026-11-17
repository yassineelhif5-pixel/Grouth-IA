"""SEO crawler against a real local HTTP site (no mocks of the crawler itself)."""
import http.server
import threading

import pytest

from apps.seo.crawler import Crawler

SITE = {
    "/robots.txt": ("text/plain", "User-agent: *\nDisallow: /private\nSitemap: http://HOST/sitemap.xml\n"),
    "/sitemap.xml": ("application/xml", '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                     "<url><loc>http://HOST/</loc></url><url><loc>http://HOST/orphan</loc></url></urlset>"),
    "/": ("text/html", '<html lang="fr"><head><title>Accueil Growth Test Site</title><meta name="viewport" content="width=device-width">'
          '<meta name="description" content="Desc"><link rel="canonical" href="http://HOST/">'
          '<script type="application/ld+json">{"@type":"Organization","name":"T"}</script></head>'
          '<body><h1>Accueil</h1><img src="a.png"><a href="/about">About</a><a href="/broken">x</a><a href="/private/x">p</a>'
          + " mot" * 300 + "</body></html>"),
    "/about": ("text/html", "<html><head><title>Accueil Growth Test Site</title></head><body><p>short</p></body></html>"),
    "/orphan": ("text/html", '<html lang="en"><head><title>Orphan page title</title></head><body><h1>O</h1></body></html>'),
}


@pytest.fixture(scope="module")
def site():
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            host = f"127.0.0.1:{self.server.server_port}"
            if self.path not in SITE:
                self.send_response(404)
                self.end_headers()
                return
            ctype, body = SITE[self.path]
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.end_headers()
            self.wfile.write(body.replace("HOST", host).encode())

        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_crawl_finds_real_issues(site):
    res = Crawler("GrowthIA-Test", max_pages=10, delay=0).crawl(site + "/")
    urls = {p.url for p in res.pages}
    codes = {(i.code, i.page_url) for i in res.issues}
    assert site + "/about" in urls and site + "/orphan" in urls
    assert any(u.endswith("/private/x") for u in res.blocked_by_robots)  # robots.txt respected
    assert ("broken_internal_link", site + "/") in codes
    assert ("http_4xx", site + "/broken") in codes
    assert ("title_duplicate", site + "/") in codes or ("title_duplicate", site + "/about") in codes
    assert ("meta_description_missing", site + "/about") in codes
    assert ("orphan_page", site + "/orphan") in codes
    assert ("img_alt_missing", site + "/") in codes
    assert ("schema_missing", site + "/") not in codes
    home = next(p for p in res.pages if p.url == site + "/")
    assert home.schema_types == ["Organization"] and home.word_count >= 300
    assert 0 <= res.score < 100
