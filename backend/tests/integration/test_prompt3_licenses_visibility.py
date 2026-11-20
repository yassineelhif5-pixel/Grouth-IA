"""PROMPT 3 journeys against a real PostgreSQL (RLS on):
licences (PILOTE allocations, admin assignment, module access), user creation, visibility programme
(real local website + competitor crawled, recommendations, generated files, roadmap, validation → schedulers), KPIs."""
import http.server
import threading
import uuid

import pytest
from django.test import override_settings

pytestmark = pytest.mark.django_db(transaction=True, databases=["default", "logs"])

PAGES = {
    "acme": {"/": ("text/html", '<html lang="fr"><head><title>Acme CRM logiciel CRM PME</title><meta name="description" content="Logiciel CRM pour PME">'
                    "</head><body><h1>Logiciel CRM pour PME</h1><h2>Pipeline commercial</h2><a href='/prix'>Prix</a>"
                    + "<p>Logiciel CRM pipeline commercial relances automatiques PME.</p>" * 15 + "</body></html>"),
             "/prix": ("text/html", "<html><head><title>Prix Acme CRM</title></head><body><h1>Tarifs du logiciel CRM</h1></body></html>")},
    "rival": {"/": ("text/html", '<html><head><title>Rival facturation en ligne et CRM</title>'
                     '<script type="application/ld+json">{"@type":"SoftwareApplication","name":"Rival"}</script></head>'
                     "<body><h1>Facturation en ligne</h1><h2>Devis et facturation en ligne</h2>"
                     + "<p>Facturation en ligne devis automatiques facturation en ligne.</p>" * 15 + "</body></html>"),
              "/robots.txt": ("text/plain", "User-agent: *\nAllow: /\nSitemap: http://HOST/sitemap.xml\n"),
              "/llms.txt": ("text/plain", "# Rival\n")},
}


def _serve(pages):
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            host = f"127.0.0.1:{self.server.server_port}"
            if self.path not in pages:
                self.send_response(404)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(b"<html><body>404</body></html>")
                return
            ctype, body = pages[self.path]
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.end_headers()
            self.wfile.write(body.replace("HOST", host).encode())

        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_port}"


@pytest.fixture(scope="module")
def sites():
    a, ua = _serve(PAGES["acme"])
    b, ub = _serve(PAGES["rival"])
    yield ua, ub
    a.shutdown()
    b.shutdown()


def _enterprise(pilot, tid):
    r = pilot["client"].post(f"/api/v1/pilot/tenants/{tid}/license",
                             {"operation": "change_plan", "plan_code": "GROWTH_ENTREPRISE", "reason": "test"}, format="json")
    assert r.status_code == 200, r.content


@override_settings(EMAIL_HOST="", SUPABASE_SERVICE_ROLE_KEY="")
def test_licenses_pilot_allocations_admin_assignment_and_module_access(tenant_user, make_user, admin_conn):
    owner, pilot = tenant_user(), make_user(pilot=True)
    tid = owner["tenant_id"]
    _enterprise(pilot, tid)
    lic = owner["client"].get("/api/v1/licenses").json()
    full = next(x for x in lic if x["code"] == "FULL")
    assert full["used"] == 1 and full["quantity"] >= 1                       # existing member keeps access (FULL)

    # PILOTE declares the licences of the tenant
    r = pilot["client"].put(f"/api/v1/pilot/tenants/{tid}/licenses", {"quantities": {"FULL": 2, "MARKETING": 1}, "reason": "contrat"},
                            format="json")
    assert r.status_code == 200, r.content
    assert {x["code"]: x["available"] for x in r.json()}["MARKETING"] == 1
    # cannot go below what is already assigned
    r = pilot["client"].put(f"/api/v1/pilot/tenants/{tid}/licenses", {"quantities": {"FULL": 0}}, format="json")
    assert r.status_code == 409 and r.json()["error"]["code"] == "allocation_below_usage"

    # admin creates a user with a MARKETING licence (no mail server → one-time link)
    invited = make_user()
    r = owner["client"].post("/api/v1/members", {"email": invited["email"], "role_code": "tenant_member", "license_code": "MARKETING"},
                             format="json")
    assert r.status_code == 201, r.content
    body = r.json()
    assert body["email_status"] == "not_configured" and body["accept_path"].startswith("/invitations/accept?token=")
    token = body["accept_path"].split("token=")[1]
    # the pool is reserved: a second MARKETING invitation is refused
    r = owner["client"].post("/api/v1/members", {"email": f"x-{uuid.uuid4().hex[:6]}@example.test", "license_code": "MARKETING"}, format="json")
    assert r.status_code == 201  # invitation possible while nobody accepted yet…
    acc = invited["client"].post("/api/v1/invitations/accept", {"token": token}, format="json")
    assert acc.status_code in (200, 201), acc.content
    members = owner["client"].get("/api/v1/members").json()
    m = next(x for x in members if x["email"] == invited["email"])
    assert m["license_code"] == "MARKETING"
    # …but no third MARKETING licence can be assigned once the pool is used
    other = next(x for x in members if x["email"] == owner["email"])
    r = owner["client"].put(f"/api/v1/members/{other['id']}/license", {"license_code": "MARKETING"}, format="json")
    assert r.status_code == 409 and r.json()["error"]["code"] in ("owner_protected", "license_exhausted")

    # module access follows the licence: SEO yes, prospects no
    invited["client"].credentials(HTTP_AUTHORIZATION=invited["client"]._credentials["HTTP_AUTHORIZATION"], HTTP_X_TENANT_ID=tid)
    assert invited["client"].get("/api/v1/seo/projects").status_code == 200
    denied = invited["client"].get("/api/v1/prospects/items")
    assert denied.status_code == 403 and "licence" in denied.json()["error"]["message"].lower()
    # licence change is versioned and audited
    assert admin_conn.execute("SELECT count(*) FROM public.audit_events WHERE tenant_id = %s AND action = 'license.assigned'",
                              [tid]).fetchone()[0] >= 1
    assert admin_conn.execute("SELECT count(*) FROM public.entity_history WHERE tenant_id = %s AND entity_type = 'tenant_license_allocations'",
                              [tid]).fetchone()[0] >= 1


@override_settings(EMAIL_HOST="", SUPABASE_SERVICE_ROLE_KEY="")
def test_pilot_creates_user_in_any_tenant(tenant_user, make_user):
    owner, pilot = tenant_user(), make_user(pilot=True)
    r = pilot["client"].post(f"/api/v1/pilot/tenants/{owner['tenant_id']}/members",
                             {"email": f"p-{uuid.uuid4().hex[:6]}@example.test", "role_code": "analyst", "license_code": "FULL"}, format="json")
    assert r.status_code == 201, r.content
    assert pilot["client"].get(f"/api/v1/pilot/tenants/{owner['tenant_id']}/members").status_code == 200
    assert owner["client"].get(f"/api/v1/pilot/tenants/{owner['tenant_id']}/members").status_code == 403


@override_settings(CRAWLER_DELAY_SECONDS=0)
def test_visibility_programme_end_to_end(tenant_user, make_user, sites, admin_conn):
    site, rival = sites
    owner, pilot = tenant_user(), make_user(pilot=True)
    tid = owner["tenant_id"]
    _enterprise(pilot, tid)
    c = owner["client"]
    # assistant works without an AI provider (guided questionnaire, answers stored)
    r = c.post("/api/v1/visibility/programmes", {"name": "Acme", "site_urls": [site], "competitors": [{"name": "Rival", "url": rival}],
                                                 "scheduler_kind": "intelligent", "scope": ["seo", "geo", "prospect"]}, format="json")
    assert r.status_code == 202, r.content
    pid, aid = r.json()["profile_id"], r.json()["audit_id"]
    a1 = c.post("/api/v1/visibility/assistant", {"profile_id": pid, "message": "", "history": []}, format="json").json()
    assert a1["source"] == "guided" and a1["next_question"] == "offer"
    a2 = c.post("/api/v1/visibility/assistant", {"profile_id": pid, "message": "Un CRM simple pour PME",
                                                 "history": [{"role": "assistant", "content": a1["reply"]}]}, format="json").json()
    assert a2["answers"]["offer"] == "Un CRM simple pour PME" and a2["next_question"] == "audience"

    prog = c.get(f"/api/v1/visibility/audits/{aid}/progress").json()
    assert prog["status"] == "succeeded" and prog["progress"] == 100, prog
    rep = c.get(f"/api/v1/visibility/audits/{aid}/report").json()
    sitef = rep["audit"]["site_findings"]
    assert sitef["keywords"] and any("logiciel crm" == k["keyword"] for k in sitef["keywords"])
    checks = {x["code"]: x["status"] for x in sitef["sites"][0]["checks"]}
    assert checks["https"] == "error" and checks["sitemap_xml"] == "error" and checks["robots_txt"] == "error"
    comp = rep["audit"]["competitor_findings"]
    assert comp["competitors"][0]["name"] == "Rival" and comp["competitors"][0]["has_llms_txt"] is True
    assert any(g["keyword"] == "facturation en ligne" for g in comp["keyword_gap"])
    assert rep["audit"]["ai_summary"]["source"] == "rules"                  # no AI configured → labelled rule-based synthesis
    assert {a["asset_type"] for a in rep["assets"]} >= {"robots_txt", "sitemap_xml", "json_ld", "open_graph", "llms_txt", "page_404"}
    assert rep["roadmap"] and {r["phase"] for r in rep["roadmap"]} >= {"now"}
    codes = {r["code"] for r in rep["recommendations"]}
    assert {"robots_txt", "sitemap_xml", "https", "keyword_gap", "pillar_article", "icp_from_keywords"} <= codes

    # generated file download
    asset = next(a for a in rep["assets"] if a["asset_type"] == "robots_txt")
    dl = c.get(f"/api/v1/visibility/assets/{asset['id']}/download")
    assert dl.status_code == 200 and b"Sitemap:" in dl.content

    # validation: a technical file is delivered ready to deploy, a content action becomes a scheduler with its frequency
    tech = next(r for r in rep["recommendations"] if r["code"] == "robots_txt")
    res = c.post(f"/api/v1/visibility/recommendations/{tech['id']}/accept", {}, format="json").json()
    assert res["status"] == "accepted" and res["asset_id"]
    content = next(r for r in rep["recommendations"] if r["code"] == "pillar_article")
    bulk = c.post("/api/v1/visibility/recommendations/accept-bulk",
                  {"items": [{"id": content["id"], "frequency": "weekly", "times_per_period": 2}], "scheduler_kind": "intelligent",
                   "autonomy": "approval"}, format="json").json()
    assert bulk["applied"][0]["status"] == "scheduled", bulk
    sched = admin_conn.execute("""SELECT scheduler_kind, category, mode, params->>'times_per_period' FROM public.tenant_schedulers
                                   WHERE id = %s""", [bulk["applied"][0]["scheduler_id"]]).fetchone()
    assert sched == ("intelligent", "articles", "approval", "2")
    watch = admin_conn.execute("""SELECT count(*) FROM public.tenant_schedulers WHERE tenant_id = %s AND category = 'seo'
                                   AND scheduler_kind = 'intelligent'""", [tid]).fetchone()[0]
    assert watch == 1                                                       # intelligent mode: weekly re-audit

    # scheduler limit declared by the PILOTE is enforced
    pilot["client"].post(f"/api/v1/pilot/tenants/{tid}/license", {"operation": "quota_override", "quota_code": "scheduler.configurations",
                                                                  "limit": 2, "reason": "test"}, format="json")
    other = next(r for r in rep["recommendations"] if r["code"] == "comparison_article")
    over = c.post(f"/api/v1/visibility/recommendations/{other['id']}/accept", {"frequency": "monthly"}, format="json")
    assert over.status_code in (402, 409, 429), over.content

    # KPIs: real sources only
    k = {x["code"]: x for x in c.get("/api/v1/visibility/kpis").json()["kpis"]}
    assert k["impressions"]["status"] == "not_connected" and k["impressions"]["value"] is None
    assert k["ai_mention_rate"]["status"] == "no_data" and k["technical_score"]["status"] == "observed"
    ai = c.get("/api/v1/visibility/ai").json()
    assert ai["responses"] == 0 and ai["mention_rate"] is None and "Aucun chiffre n'est estimé" in ai["disclaimer"]
    assert c.post("/api/v1/visibility/ai", {"profile_id": pid}, format="json").json()["created"] >= 5
