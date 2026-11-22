"""Blog autopilot end to end (WordPress and AI simulated): CMS connector, themes and categories, conversation with the
publication assistant, explicit confirmation kept in the history, scheduled run writing a new article and publishing
it on WordPress, 'validation first' mode, pause/resume — tenant isolated."""
import json

import pytest
import responses

from .test_prompt2_journeys import AI, configure_ai, upgrade

pytestmark = pytest.mark.django_db(transaction=True, databases=["default", "logs"])
WP = "https://blog.test"


def _ai(r, text):
    r.add(responses.POST, AI, json={"choices": [{"message": {"role": "assistant", "content": text}}],
                                    "usage": {"prompt_tokens": 100, "completion_tokens": 50}})


def _setup(tenant_user, client):
    a = tenant_user()
    upgrade(client, a["tenant_id"])
    c = a["client"]
    product = c.post("/api/v1/products", {"name": "Smart Tower", "slug": "smart-tower", "description": "Pilotage de projets BTP."},
                     format="json").json()
    conn = c.post("/api/v1/connectors/connect", {"provider_code": "wordpress"}, format="json").json()
    r = c.post(f"/api/v1/connector-accounts/{conn['account_id']}/credentials",
               {"credential_type": "basic", "secrets": {"username": "growth", "application_password": "abcd efgh ijkl mnop qrst uvwx"},
                "settings": {"site_url": WP}}, format="json")
    assert r.status_code in (200, 201), r.content
    return a, c, product, conn["account_id"]


def _converse(c, plan):
    seen = []
    for msg in ["", "2 articles par semaine", "le mardi à 9h30", "plutôt long", "ton pédagogique", "publie directement sur le site"]:
        r = c.post("/api/v1/content/autopilot/chat", {"message": msg, "plan": plan, "history": seen}, format="json").json()
        plan = r["plan"]
        seen += [{"role": "user", "content": msg}, {"role": "assistant", "content": r["reply"]}]
    return r


def test_blog_autopilot_end_to_end(tenant_user, client, admin_conn):
    a, c, product, account = _setup(tenant_user, client)
    with responses.RequestsMock(assert_all_requests_are_fired=False) as web:
        web.add_passthru("http://127.0.0.1")
        web.add(responses.GET, f"{WP}/wp-json/wp/v2/categories", json=[{"id": 7, "name": "Actualités"}, {"id": 9, "name": "Guides"}])
        setup = c.get("/api/v1/content/autopilot/setup", {"product_id": product["id"], "account_id": account}).json()
    assert [x["provider"] for x in setup["accounts"]] == ["wordpress"] and setup["categories"][1]["name"] == "Guides"
    assert setup["themes"]["method"] == "rules" and len(setup["themes"]["themes"]) >= 5

    # the assistant asks the missing questions one by one (no AI configured: guided dialogue), then recaps
    r = _converse(c, {"account_id": account, "product_id": product["id"], "theme": "Digitaliser le suivi de chantier", "category_ids": [9]})
    assert r["ready"] is True and r["plan"] == {**r["plan"], "frequency": "weekly", "per_period": 2, "day": 2, "time": "09:30",
                                                "words": 2000, "tone": "pédagogique", "publish_mode": "publish"}
    assert "Confirmez-vous" in r["reply"]
    incomplete = c.post("/api/v1/content/autopilot/confirm", {"plan": {**r["plan"], "tone": None, "publish_mode": None}}, format="json")
    assert incomplete.status_code == 400 or incomplete.json()["error"]["code"] in ("plan_incomplete",)

    conf = c.post("/api/v1/content/autopilot/confirm", {"plan": r["plan"]}, format="json").json()
    assert conf["scheduler_id"] and conf["confirmation"].startswith("Programme confirmé")
    sched = admin_conn.execute("SELECT category, frequency_type, frequency_value, mode, params FROM public.tenant_schedulers WHERE id = %s",
                               [conf["scheduler_id"]]).fetchone()
    assert sched[:4] == ("articles", "every_x_hours", "84", "automatic") and sched[4]["autopilot"] is True

    # one run: a new article with the AI's own title, published on WordPress in the chosen category
    configure_ai(admin_conn)
    with responses.RequestsMock(assert_all_requests_are_fired=False) as web:
        web.add_passthru("http://127.0.0.1")
        _ai(web, "# Suivi de chantier : 7 étapes pour digitaliser\n\n## Pourquoi\n\nTexte de l'article.\n\n## FAQ\n\n**Combien ?** Réponse.")
        web.add(responses.POST, f"{WP}/wp-json/wp/v2/posts", json={"id": 42, "link": f"{WP}/suivi-de-chantier"})
        run = c.post(f"/api/v1/content/autopilot/{conf['scheduler_id']}/run", {}, format="json")
        assert run.status_code == 200, run.content
        wp = [x for x in web.calls if x.request.url.endswith("/wp-json/wp/v2/posts")]
        assert len(wp) == 1
        sent = json.loads(wp[0].request.body)
        assert sent["title"] == "Suivi de chantier : 7 étapes pour digitaliser" and sent["status"] == "publish" and sent["categories"] == [9]
        assert "<h1>" not in sent["content"] and wp[0].request.headers["Authorization"].startswith("Basic ")

    h = c.get("/api/v1/content/autopilot/history").json()
    assert h["plans"][0]["id"] == conf["scheduler_id"]
    art = h["articles"][0]
    assert art["publication_status"] == "published" and art["external_url"] == f"{WP}/suivi-de-chantier"
    assert any(e["event_type"] == "content.autopilot_confirmed" for e in h["events"])

    # pause / resume are recorded too
    assert c.post(f"/api/v1/content/autopilot/{conf['scheduler_id']}/pause", {}, format="json").json()["status"] == "paused"
    assert c.post(f"/api/v1/content/autopilot/{conf['scheduler_id']}/resume", {}, format="json").json()["status"] == "active"
    events = [e["event_type"] for e in c.get("/api/v1/content/autopilot/history").json()["events"]]
    assert "content.autopilot_paused" in events and "content.autopilot_resumed" in events


def test_validation_first_mode_waits_then_publishes(tenant_user, client, admin_conn):
    a, c, product, account = _setup(tenant_user, client)
    plan = {"account_id": account, "product_id": product["id"], "theme": "Réglementation BTP 2026", "frequency": "weekly", "per_period": 1,
            "day": 4, "time": "08:00", "words": 1200, "tone": "expert", "publish_mode": "approval"}
    conf = c.post("/api/v1/content/autopilot/confirm", {"plan": plan}, format="json").json()
    assert admin_conn.execute("SELECT mode, frequency_type, frequency_value FROM public.tenant_schedulers WHERE id = %s",
                              [conf["scheduler_id"]]).fetchone() == ("approval", "weekly", "3 08:00")
    configure_ai(admin_conn)
    with responses.RequestsMock(assert_all_requests_are_fired=False) as web:
        web.add_passthru("http://127.0.0.1")
        _ai(web, "# Réglementation : ce qui change\n\nTexte.")
        web.add(responses.POST, f"{WP}/wp-json/wp/v2/posts", json={"id": 7, "link": f"{WP}/reglementation"})
        c.post(f"/api/v1/content/autopilot/{conf['scheduler_id']}/run", {}, format="json")
        art = c.get("/api/v1/content/autopilot/history").json()["articles"][0]
        assert art["publication_status"] is None and not [x for x in web.calls if "/wp/v2/posts" in x.request.url]  # waits
        pub = c.post(f"/api/v1/content/autopilot/{art['id']}/publish", {}, format="json").json()
        assert pub["status"] == "published" and pub["url"] == f"{WP}/reglementation"


def test_autopilot_is_tenant_isolated(tenant_user, client):
    _, c, product, account = _setup(tenant_user, client)
    b = tenant_user()
    upgrade(client, b["tenant_id"])
    plan = {"account_id": account, "product_id": product["id"], "theme": "x", "frequency": "daily", "per_period": 1, "time": "09:00",
            "words": 700, "tone": "expert", "publish_mode": "draft"}
    r = b["client"].post("/api/v1/content/autopilot/confirm", {"plan": plan}, format="json")
    assert r.status_code == 404  # another tenant's connector is invisible
    assert b["client"].get("/api/v1/content/autopilot/setup").json()["accounts"] == []
