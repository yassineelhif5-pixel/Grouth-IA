"""PILOTE full access, invitations without a mail server, paid offers, end of trial (read-only) and the cron tick
that replaces Celery Beat on serverless hosting — against a real PostgreSQL with RLS on."""
import uuid

import pytest
from django.test import override_settings

pytestmark = pytest.mark.django_db(transaction=True, databases=["default", "logs"])


def _slug():
    return "it-" + uuid.uuid4().hex[:10]


def test_pilot_creates_tenant_and_gets_full_access(make_user, admin_conn):
    pilot = make_user(pilot=True)
    r = pilot["client"].post("/api/v1/pilot/tenants", {"name": "Client A", "slug": _slug(), "plan_code": "OFFRE_PRO"}, format="json")
    assert r.status_code == 201, r.content
    tid = r.json()["id"]
    role = admin_conn.execute("""SELECT r.code, ms.granted_reason FROM public.tenant_members m
                                   JOIN public.tenant_memberships ms ON ms.member_id = m.id AND ms.deleted_at IS NULL
                                   JOIN public.tenant_roles r ON r.id = ms.role_id
                                  WHERE m.tenant_id = %s AND m.user_id = %s""", [tid, pilot["id"]]).fetchone()
    assert role == ("tenant_owner", "PILOTE support access")
    # entering is idempotent and the pilot then works inside the tenant like its owner
    again = pilot["client"].post(f"/api/v1/pilot/tenants/{tid}/enter", {}, format="json")
    assert again.status_code == 200 and again.json() == {"tenant_id": tid, "granted": False}
    pilot["client"].credentials(HTTP_AUTHORIZATION=pilot["client"]._credentials["HTTP_AUTHORIZATION"], HTTP_X_TENANT_ID=tid)
    lic = pilot["client"].get("/api/v1/license").json()
    assert lic["subscription"]["plan"] == "OFFRE_PRO"
    assert admin_conn.execute("SELECT count(*) FROM public.audit_events WHERE tenant_id = %s AND action = 'pilot.tenant.access_granted'",
                              [tid]).fetchone()[0] == 1


def test_pilot_enter_requires_platform_role(tenant_user):
    a = tenant_user()
    assert a["client"].post(f"/api/v1/pilot/tenants/{a['tenant_id']}/enter", {}, format="json").status_code == 403


def test_duplicate_slug_is_a_clear_conflict(make_user):
    pilot, slug = make_user(pilot=True), _slug()
    assert pilot["client"].post("/api/v1/pilot/tenants", {"name": "A", "slug": slug}, format="json").status_code == 201
    r = pilot["client"].post("/api/v1/pilot/tenants", {"name": "B", "slug": slug}, format="json")
    assert r.status_code == 409 and r.json()["error"]["code"] == "slug_taken"


@override_settings(EMAIL_HOST="")
def test_invitation_returns_one_time_link_without_mail_server(tenant_user):
    a = tenant_user()
    r = a["client"].post("/api/v1/invitations", {"email": f"new-{uuid.uuid4().hex[:6]}@example.test", "role_code": "seo_manager"},
                         format="json")
    assert r.status_code == 201, r.content
    assert r.json()["accept_path"].startswith("/invitations/accept?token=")


def test_paid_offers_catalogue_and_checkout_without_stripe(tenant_user):
    a = tenant_user()
    plans = a["client"].get("/api/v1/billing/plans").json()
    assert [(p["code"], p["price_monthly_cents"]) for p in plans["plans"]] == [
        ("OFFRE_STARTER", 2000), ("OFFRE_PRO", 5000), ("OFFRE_PROFESSIONNELLE", 20000)]
    with override_settings(STRIPE_SECRET_KEY=""):
        r = a["client"].post("/api/v1/billing/checkout", {"plan_code": "OFFRE_PRO"}, format="json")
    assert r.status_code == 409 and r.json()["error"]["code"] == "billing_not_configured"


def test_expired_trial_makes_the_space_read_only_but_payable(tenant_user, make_user, admin_conn):
    a = tenant_user()
    admin_conn.execute("""UPDATE public.tenant_subscriptions SET trial_ends_at = now() - interval '1 minute'
                           WHERE tenant_id = %s AND deleted_at IS NULL""", [a["tenant_id"]])
    assert a["client"].get("/api/v1/products").status_code == 200  # reading stays possible
    w = a["client"].post("/api/v1/products", {"name": "Après essai", "slug": "apres-essai"}, format="json")
    assert w.status_code == 402 and w.json()["error"]["code"] == "subscription_inactive"
    with override_settings(STRIPE_SECRET_KEY=""):  # paying is never blocked by the read-only mode
        pay = a["client"].post("/api/v1/billing/checkout", {"plan_code": "OFFRE_STARTER"}, format="json")
    assert pay.json()["error"]["code"] == "billing_not_configured"
    # the PILOTE is never blocked by a tenant's subscription
    pilot = make_user(pilot=True)
    assert pilot["client"].post(f"/api/v1/pilot/tenants/{a['tenant_id']}/enter", {}, format="json").status_code == 200
    pilot["client"].credentials(HTTP_AUTHORIZATION=pilot["client"]._credentials["HTTP_AUTHORIZATION"], HTTP_X_TENANT_ID=a["tenant_id"])
    assert pilot["client"].post("/api/v1/products", {"name": "Par le pilote", "slug": "par-le-pilote"}, format="json").status_code == 201


def test_cron_tick_requires_secret_and_runs_each_period_once(client, admin_conn):
    with override_settings(CRON_SECRET=""):
        assert client.get("/api/v1/internal/cron/tick").status_code == 503
    with override_settings(CRON_SECRET="cron-test-secret"):
        assert client.get("/api/v1/internal/cron/tick", HTTP_AUTHORIZATION="Bearer wrong").status_code == 403
        first = client.get("/api/v1/internal/cron/tick", HTTP_AUTHORIZATION="Bearer cron-test-secret")
        assert first.status_code == 200, first.content
        tasks = first.json()["tasks"]
        assert tasks["scheduler-dispatch"] in ("ok", "already_done") and "expire-trials" in tasks
        assert not [k for k, v in tasks.items() if v == "unknown_task"]
        second = client.get("/api/v1/internal/cron/tick", HTTP_AUTHORIZATION="Bearer cron-test-secret").json()["tasks"]
        assert second["ensure-partitions"] == "already_done"  # daily task: never twice in the same period
