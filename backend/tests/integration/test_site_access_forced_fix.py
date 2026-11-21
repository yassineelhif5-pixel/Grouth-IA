"""Forced correction against a local GitHub API double: real HTTP calls, real commit/PR payloads checked."""
import http.server
import json
import threading

import pytest

from apps.integrations import providers

from .test_prompt3_licenses_visibility import _enterprise, sites  # noqa: F401 — reuse the local test sites fixture

pytestmark = pytest.mark.django_db(transaction=True, databases=["default", "logs"])

TOKEN = "github_pat_" + "A" * 40


class FakeGitHub(http.server.BaseHTTPRequestHandler):
    calls: list = []

    def _send(self, code, body):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def _auth(self):
        return self.headers.get("Authorization") == f"Bearer {TOKEN}"

    def do_GET(self):
        FakeGitHub.calls.append(("GET", self.path, None))
        if not self._auth():
            return self._send(401, {"message": "Bad credentials"})
        if self.path == "/user":
            return self._send(200, {"login": "acme"})
        if self.path.startswith("/user/repos"):
            return self._send(200, [{"full_name": "acme/site", "default_branch": "main", "private": True, "permissions": {"push": True}},
                                    {"full_name": "other/ro", "default_branch": "main", "permissions": {"push": False}}])
        if self.path == "/repos/acme/site":
            return self._send(200, {"full_name": "acme/site", "default_branch": "main", "permissions": {"push": True}})
        if self.path == "/repos/acme/site/git/ref/heads/main":
            return self._send(200, {"object": {"sha": "basesha"}})
        if self.path == "/repos/acme/site/git/commits/basesha":
            return self._send(200, {"tree": {"sha": "basetree"}})
        return self._send(404, {"message": "Not Found"})

    def _body(self):
        return json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")

    def do_POST(self):
        body = self._body()
        FakeGitHub.calls.append(("POST", self.path, body))
        if self.path == "/repos/acme/site/git/trees":
            return self._send(201, {"sha": "newtree"})
        if self.path == "/repos/acme/site/git/commits":
            return self._send(201, {"sha": "newcommit"})
        if self.path == "/repos/acme/site/git/refs":
            return self._send(201, {"ref": body["ref"]})
        if self.path == "/repos/acme/site/pulls":
            return self._send(201, {"number": 7, "html_url": "https://github.com/acme/site/pull/7"})
        return self._send(404, {})

    def do_PATCH(self):
        body = self._body()
        FakeGitHub.calls.append(("PATCH", self.path, body))
        return self._send(200, {"object": {"sha": body.get("sha")}})

    def log_message(self, *a):
        pass


@pytest.fixture
def github(monkeypatch):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeGitHub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(providers, "GITHUB_API", f"http://127.0.0.1:{srv.server_port}")
    FakeGitHub.calls = []
    yield FakeGitHub
    srv.shutdown()


def test_forced_correction_via_github(tenant_user, make_user, sites, github, admin_conn):  # noqa: F811
    site, rival = sites
    owner, pilot = tenant_user(), make_user(pilot=True)
    _enterprise(pilot, owner["tenant_id"])
    c = owner["client"]
    aid = c.post("/api/v1/visibility/programmes", {"name": "Acme", "site_urls": [site], "scope": ["seo"]}, format="json").json()["audit_id"]
    recs = {r["code"]: r for r in c.get(f"/api/v1/visibility/audits/{aid}/report").json()["recommendations"]}

    st = c.get("/api/v1/visibility/site-access").json()
    assert st["accounts"] == [] and st["oauth_available"] is False
    # without the PILOTE's OAuth app, one-click is refused with a clear message; a bad token is refused
    assert c.post("/api/v1/visibility/site-access", {}, format="json").json()["error"]["code"] == "oauth_not_configured"
    assert c.post("/api/v1/visibility/site-access", {"token": "nope"}, format="json").status_code == 400
    con = c.post("/api/v1/visibility/site-access", {"token": TOKEN, "return_to": f"/t/{owner['tenant_id']}/visibility"}, format="json")
    assert con.status_code == 200, con.content
    acc = con.json()["account_id"]
    repos = c.get(f"/api/v1/visibility/site-access/{acc}").json()
    assert [r["full_name"] for r in repos] == ["acme/site"]                 # only repositories the user can write to
    cfg = c.put(f"/api/v1/visibility/site-access/{acc}", {"repo": "acme/site", "base_path": "public", "mode": "pull_request"}, format="json")
    assert cfg.status_code == 200 and cfg.json()["branch"] == "main", cfg.content
    secret = admin_conn.execute("SELECT ciphertext FROM public.tenant_connector_credentials WHERE account_id = %s AND deleted_at IS NULL",
                                [acc]).fetchone()[0]
    assert TOKEN not in secret                                              # stored encrypted

    ids = [recs["robots_txt"]["id"], recs["sitemap_xml"]["id"], recs["json_ld"]["id"]] if "json_ld" in recs else \
          [recs["robots_txt"]["id"], recs["sitemap_xml"]["id"]]
    res = c.post("/api/v1/visibility/site-access/apply", {"account_id": acc, "recommendation_ids": ids}, format="json")
    assert res.status_code == 200, res.content
    out = res.json()
    assert out["mode"] == "pull_request" and out["pull_request"] == 7 and out["url"].endswith("/pull/7")
    tree = next(b for m, p, b in github.calls if p.endswith("/git/trees"))
    paths = {t["path"] for t in tree["tree"]}
    assert {"public/robots.txt", "public/sitemap.xml"} <= paths and tree["base_tree"] == "basetree"
    assert "Sitemap:" in next(t["content"] for t in tree["tree"] if t["path"] == "public/robots.txt")
    assert not any(m == "PATCH" for m, _, _ in github.calls)               # PR mode never touches the branch
    ex = {x["id"]: x for x in c.get("/api/v1/visibility/recommendations/execution", {"audit_id": aid}).json()}
    assert ex[recs["robots_txt"]["id"]]["state"] == "succeeded" and ex[recs["robots_txt"]["id"]]["link"].endswith("/pull/7")

    # direct replacement, explicitly chosen
    github.calls = []
    d = c.post("/api/v1/visibility/site-access/apply", {"account_id": acc, "recommendation_ids": ids[:1], "mode": "direct"}, format="json").json()
    assert d["mode"] == "direct" and d["branch"] == "main"
    patch = next(b for m, p, b in github.calls if m == "PATCH")
    assert patch == {"sha": "newcommit", "force": False}

    # a PILOTE suspension is respected
    admin_conn.execute("""UPDATE public.tenant_connector_authorizations SET status = 'suspended' WHERE tenant_id = %s
                          AND provider_id = (SELECT id FROM public.connector_providers WHERE code = 'github')""", [owner["tenant_id"]])
    assert c.post("/api/v1/visibility/site-access", {"token": TOKEN}, format="json").status_code == 403


def _connect_and_configure(c):
    """Connect GitHub by token and point it at acme/site (helper shared by the forced-push tests)."""
    acc = c.post("/api/v1/visibility/site-access", {"token": TOKEN}, format="json").json()["account_id"]
    c.put(f"/api/v1/visibility/site-access/{acc}", {"repo": "https://github.com/acme/site", "base_path": "public", "mode": "direct"}, format="json")
    return acc


def test_forced_correction_pushes_through_scheduler(tenant_user, make_user, sites, github, admin_conn):  # noqa: F811
    site, _rival = sites
    owner, pilot = tenant_user(), make_user(pilot=True)
    _enterprise(pilot, owner["tenant_id"])
    c = owner["client"]
    aid = c.post("/api/v1/visibility/programmes", {"name": "Acme", "site_urls": [site], "scope": ["seo"]}, format="json").json()["audit_id"]
    robots = next(x for x in c.get(f"/api/v1/visibility/audits/{aid}/report").json()["recommendations"] if x["code"] == "robots_txt")
    _connect_and_configure(c)
    # a full URL was accepted and normalised to owner/name
    assert admin_conn.execute("""SELECT settings->>'repo' FROM public.tenant_connector_accounts a
                                  JOIN public.connector_providers p ON p.id=a.provider_id
                                  WHERE a.tenant_id=%s AND p.code='github'""", [owner["tenant_id"]]).fetchone()[0] == "acme/site"

    github.calls = []
    bulk = c.post("/api/v1/visibility/recommendations/accept-bulk",
                  {"autonomy": "automatic", "items": [{"id": robots["id"], "frequency": "once", "run_now": True, "forced": True}]},
                  format="json").json()
    applied = bulk["applied"][0]
    assert applied["status"] == "scheduled" and applied["forced"] is True and applied["run_id"]
    cat = admin_conn.execute("SELECT category FROM public.tenant_schedulers WHERE id=%s", [applied["scheduler_id"]]).fetchone()[0]
    assert cat == "site_files"
    # the scheduler run actually pushed the file to GitHub, replacing the existing one (direct mode → PATCH ref)
    tree = next(b for m, p, b in github.calls if p.endswith("/git/trees"))
    assert any(t["path"] == "public/robots.txt" and "Sitemap:" in t["content"] for t in tree["tree"])
    assert any(m == "PATCH" for m, _p, _b in github.calls)
    # recommendation marked applied with the push result, visible in the execution view
    ex = {x["id"]: x for x in c.get("/api/v1/visibility/recommendations/execution", {"audit_id": aid}).json()}[robots["id"]]
    assert ex["state"] == "succeeded" and ex["link"] and "acme/site" in ex["link"]
    assert admin_conn.execute("SELECT status FROM public.visibility_recommendations WHERE id=%s", [robots["id"]]).fetchone()[0] == "applied"

    # re-running on demand pushes again (keeps the site in sync)
    github.calls = []
    again = c.post(f"/api/v1/visibility/recommendations/{robots['id']}/run-now", {}, format="json")
    assert again.status_code == 200
    assert any(p.endswith("/git/commits") for _m, p, _b in github.calls)
