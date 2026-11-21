"""Prospect hunting end to end, external services simulated: keyword scan, open-data company search, role-based contacts
from the company site (nominative addresses ignored), explainable score, reviewed e-mail with tracked trial link and
unsubscribe link, follow-up in the same thread, reply / click / unsubscribe recorded in the prospect history."""
import json
import re

import pytest
import responses

from .test_prompt2_journeys import _inbound, _postmark_mailbox, upgrade

pytestmark = pytest.mark.django_db(transaction=True, databases=["default", "logs"])

PRODUCT_SITE = """<html><head><title>Growth Studio - logiciel de prospection et SEO pour PME</title>
<meta name="description" content="Automatisez votre prospection B2B et votre SEO grâce à l'IA."></head>
<body><h1>Prospection B2B automatisée</h1><h2>SEO et prospection pilotés par l'IA</h2>
<p>Notre logiciel de prospection trouve vos clients. Prospection B2B, SEO local, prospection B2B.</p>
<a href="/tarifs">Tarifs</a><a href="https://ailleurs.test/x">externe</a></body></html>"""
TARIFS = "<html><head><title>Tarifs prospection B2B</title></head><body><h1>Tarifs du logiciel de prospection</h1></body></html>"
CLIENT_CONTACT = """<html><body><p>Écrivez-nous : <a href="mailto:contact@acme-client.test">contact</a>,
commercial@acme-client.test. Notre CEO : jean.dupont@acme-client.test. Prestataire : contact@agence-tierce.test</p></body></html>"""
COMPANY_API = {"results": [{"siren": "552100554", "nom_complet": "ACME INDUSTRIES", "categorie_entreprise": "GE",
                            "activite_principale": "62.01Z", "libelle_activite_principale": "Programmation informatique, prospection",
                            "tranche_effectif_salarie": "52", "siege": {"libelle_commune": "PARIS", "code_postal": "75008"},
                            "dirigeants": [{"nom": "MARTIN", "prenoms": "Claire", "qualite": "Président"}]}], "total_results": 1}


@pytest.fixture
def web():
    with responses.RequestsMock(assert_all_requests_are_fired=False) as r:
        r.add_passthru("http://127.0.0.1")
        r.add(responses.GET, "https://growth.test/robots.txt", body="User-agent: *\nAllow: /\n")
        r.add(responses.GET, "https://growth.test/", body=PRODUCT_SITE, content_type="text/html")
        r.add(responses.GET, "https://growth.test/tarifs", body=TARIFS, content_type="text/html")
        r.add(responses.GET, "https://recherche-entreprises.api.gouv.fr/search", json=COMPANY_API)
        r.add(responses.GET, "https://acme-client.test/robots.txt", body="User-agent: *\nDisallow: /mentions-legales\n")
        r.add(responses.GET, "https://acme-client.test/contact", body=CLIENT_CONTACT, content_type="text/html")
        r.add(responses.GET, re.compile(r"https://acme-client\.test/(?!contact$|robots).*"), status=404)
        r.add(responses.POST, "https://api.postmarkapp.com/email", json={"MessageID": "pm-hunt-1"})
        yield r


def test_prospect_hunt_end_to_end(tenant_user, client, admin_conn, web):
    a = tenant_user()
    upgrade(client, a["tenant_id"])
    c = a["client"]
    product = c.post("/api/v1/products", {"name": "Growth Studio", "slug": "growth-studio",
                                          "description": "Logiciel de prospection et SEO pour PME, piloté par l'IA."}, format="json").json()

    # 1. keywords really present on the site, weighted, + suggestions (rules: no AI configured here)
    kw = c.post("/api/v1/prospects/hunt/keywords", {"url": "https://growth.test"}, format="json").json()
    words = [k["keyword"] for k in kw["keywords"]]
    assert "prospection" in words[:3] and "prospection b2b" in words and len(kw["pages_scanned"]) == 2
    assert kw["suggestions_method"] == "rules" and kw["suggestions"] and all(s["keyword"] not in words for s in kw["suggestions"])

    # 2. open-data company search, then the selected company becomes a scored prospect (officer stored without e-mail)
    found = c.get("/api/v1/prospects/hunt/companies", {"q": "prospection", "category": "GE"}).json()
    assert found["results"][0]["category_label"] == "Grand groupe" and found["results"][0]["officers"][0]["name"] == "Claire MARTIN"
    added = c.post("/api/v1/prospects/hunt/companies/add", {"companies": found["results"], "product_id": product["id"]}, format="json").json()
    assert added["created"] == 1
    again = c.post("/api/v1/prospects/hunt/companies/add", {"companies": found["results"]}, format="json").json()
    assert again == {"created": 0, "already_known": 1, "prospect_ids": added["prospect_ids"]}  # deduplicated by SIREN
    pid = added["prospect_ids"][0]

    # 3. only role-based addresses of the company's own domain; robots.txt respected; nominative / third-party ignored
    sc = c.post(f"/api/v1/prospects/hunt/{pid}/site-contacts", {"domain": "acme-client.test"}, format="json").json()
    assert sc["emails"] == ["commercial@acme-client.test", "contact@acme-client.test"]
    assert not any("mentions-legales" in u for u in sc["pages_checked"])
    assert not [call for call in web.calls if call.request.url.endswith("/mentions-legales")]
    assert c.post(f"/api/v1/prospects/hunt/{pid}/enrich", {}, format="json").json()["error"]["code"] == "enrichment_not_configured"

    # 4. explainable score: big group + sector fit + identified decision maker + reachable
    board = c.get("/api/v1/prospects/hunt/board").json()
    card = next(b for b in board if b["id"] == pid)
    assert float(card["score"]) >= 70 and "Grand groupe" in card["need_detected"] and len(card["contacts"]) == 3

    # 5. pre-filled e-mail shown before sending: trial link, sender identity, unsubscribe link
    d = c.post(f"/api/v1/prospects/hunt/{pid}/draft", {}, format="json").json()
    assert d["to"] == "commercial@acme-client.test" and "ACME INDUSTRIES" in d["subject"]
    assert "/public/prospects/go/" in d["body"] and "/public/prospects/unsubscribe/" in d["body"] and "2 jours" in d["body"]
    mb = _postmark_mailbox(c, admin_conn, a["tenant_id"])
    no_unsub = c.post(f"/api/v1/prospects/hunt/{pid}/send", {"mailbox_id": mb["id"], "to": d["to"], "subject": d["subject"],
                                                              "body": "Sans lien"}, format="json")
    assert no_unsub.json()["error"]["code"] == "unsubscribe_link_required"
    edited = d["body"].replace("Bien cordialement", "Très cordialement")  # the user reviewed and edited it
    sent = c.post(f"/api/v1/prospects/hunt/{pid}/send", {"mailbox_id": mb["id"], "to": d["to"], "subject": d["subject"],
                                                          "body": edited}, format="json").json()
    assert sent["follow_up"] is False
    postmark = json.loads(web.calls[-1].request.body)
    assert "Très cordialement" in postmark["TextBody"] and postmark["To"] == "commercial@acme-client.test"

    # 6. the prospect replies (threaded), clicks the trial link, a follow-up goes in the same thread
    out = admin_conn.execute("SELECT message_id_header FROM public.email_messages WHERE prospect_id = %s AND direction = 'outbound'",
                             [pid]).fetchone()[0]
    _inbound(client, mb["id"], "<rep-hunt@acme-client.test>", out, "Bonjour, pouvez-vous nous en dire plus ?", frm="commercial@acme-client.test")
    go = re.search(r"/api/v1/public/prospects/go/(\S+)", d["body"]).group(0)
    redirect = client.get(go)
    assert redirect.status_code == 302 and redirect["Location"].endswith("/signup")
    follow = c.post(f"/api/v1/prospects/hunt/{pid}/send", {"mailbox_id": mb["id"], "to": d["to"], "subject": "Re: " + d["subject"],
                                                            "body": edited}, format="json").json()
    assert follow["follow_up"] is True
    h = c.get(f"/api/v1/prospects/hunt/{pid}/history").json()
    assert h["summary"]["sent"] == 2 and h["summary"]["replied"] is True and h["summary"]["contact_request"] is True
    assert h["summary"]["trial_clicks"] == 1 and h["summary"]["last_sent_at"]
    assert admin_conn.execute("SELECT status FROM public.prospects WHERE id = %s", [pid]).fetchone()[0] in ("interested", "replied")

    # 7. one-click unsubscribe: suppression list, contact opted out, further sending refused, history kept
    unsub = re.search(r"/api/v1/public/prospects/unsubscribe/(\S+)", d["body"]).group(0)
    assert client.get(unsub).status_code == 200
    again = c.post(f"/api/v1/prospects/hunt/{pid}/send", {"mailbox_id": mb["id"], "to": d["to"], "subject": "x", "body": edited}, format="json")
    assert again.status_code == 409
    assert any(e["summary"].startswith("Désinscription") for e in c.get(f"/api/v1/prospects/hunt/{pid}/history").json()["events"])


def test_hunt_links_are_signed_and_tenant_isolated(tenant_user, client):
    a, b = tenant_user(), tenant_user()
    assert client.get("/api/v1/public/prospects/go/forged-token").status_code == 404
    assert b["client"].get("/api/v1/prospects/hunt/00000000-0000-0000-0000-000000000000/history").status_code in (403, 404)
    assert a["client"].post("/api/v1/prospects/hunt/keywords", {"url": ""}, format="json").status_code in (400, 403)
