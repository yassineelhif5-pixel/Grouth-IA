"""End-to-end API tests: authentication, multi-tenant isolation, licences, traceability."""
import uuid

import pytest

pytestmark = pytest.mark.django_db(transaction=True, databases=["default", "logs"])


def test_requires_valid_jwt(client):
    assert client.get("/api/v1/me").status_code == 401
    r = client.get("/api/v1/me", HTTP_AUTHORIZATION="Bearer not-a-jwt")
    assert r.status_code == 401


def test_demo_signup_once_per_user(make_user):
    u = make_user()
    ok = u["client"].post("/api/v1/signup/demo", {"tenant_name": "A", "slug": "a-" + uuid.uuid4().hex[:8]}, format="json")
    assert ok.status_code == 201
    again = u["client"].post("/api/v1/signup/demo", {"tenant_name": "B", "slug": "b-" + uuid.uuid4().hex[:8]}, format="json")
    assert again.status_code == 409 and again.json()["error"]["code"] == "demo_already_used"


def test_tenant_header_is_verified_not_trusted(tenant_user):
    from rest_framework.test import APIClient

    a, b = tenant_user(), tenant_user()
    intruder = APIClient()  # A's valid JWT, but B's tenant id in the header
    intruder.credentials(HTTP_AUTHORIZATION=a["client"]._credentials["HTTP_AUTHORIZATION"], HTTP_X_TENANT_ID=b["tenant_id"])
    r = intruder.get("/api/v1/products")
    assert r.status_code == 404  # existence of B is not even revealed


def test_products_isolation_history_and_correlation(tenant_user):
    a, b = tenant_user(), tenant_user()
    corr = str(uuid.uuid4())
    created = a["client"].post("/api/v1/products", {"name": "P", "slug": "p"}, format="json", HTTP_X_CORRELATION_ID=corr)
    assert created.status_code == 201, created.content
    pid = created.json()["id"]
    upd = a["client"].patch(f"/api/v1/products/{pid}", {"name": "P2", "version_number": 1, "change_reason": "rename"}, format="json")
    assert upd.status_code == 200 and upd.json()["version_number"] == 2
    stale = a["client"].patch(f"/api/v1/products/{pid}", {"name": "P3", "version_number": 1}, format="json")
    assert stale.status_code == 409  # optimistic concurrency
    assert b["client"].get(f"/api/v1/products/{pid}").status_code == 404
    versions = a["client"].get(f"/api/v1/history/entities/products/{pid}/versions").json()
    assert [v["operation"] for v in versions] == ["UPDATE", "INSERT"] and versions[0]["change_reason"] == "rename"
    assert b["client"].get(f"/api/v1/history/entities/products/{pid}/versions").json() == []
    trace = a["client"].get(f"/api/v1/history/trace/{corr}").json()
    assert trace["audit_events"] and trace["entity_history"]
    events = b["client"].get("/api/v1/history/events", {"entity_id": pid}).json()
    assert events["results"] == []


def test_demo_quota_three_schedulers(tenant_user):
    a = tenant_user()
    for i in range(3):
        assert a["client"].post("/api/v1/schedulers", {"name": f"s{i}"}, format="json").status_code == 201
    r = a["client"].post("/api/v1/schedulers", {"name": "s4"}, format="json")
    assert r.status_code == 402 and r.json()["error"]["code"] == "quota_exceeded"


def test_soft_delete_and_restore_create_versions(tenant_user):
    a = tenant_user()
    pid = a["client"].post("/api/v1/products", {"name": "D", "slug": "d"}, format="json").json()["id"]
    assert a["client"].delete(f"/api/v1/products/{pid}?reason=test").status_code == 204
    assert a["client"].post(f"/api/v1/products/{pid}/restore", {"reason": "oops"}, format="json").status_code == 200
    ops = [v["operation"] for v in a["client"].get(f"/api/v1/history/entities/products/{pid}/versions").json()]
    assert ops == ["RESTORE", "SOFT_DELETE", "INSERT"]


def test_pilot_console_requires_platform_role(tenant_user, make_user):
    a = tenant_user()
    assert a["client"].get("/api/v1/pilot/tenants").status_code == 403
    pilot = make_user(pilot=True)
    r = pilot["client"].get("/api/v1/pilot/tenants")
    assert r.status_code == 200
    s = pilot["client"].post(f"/api/v1/pilot/tenants/{a['tenant_id']}/suspend", {"reason": "test"}, format="json")
    assert s.status_code == 200 and s.json()["status"] == "suspended"
    assert a["client"].get("/api/v1/products").status_code == 403  # suspended tenant
    audit = pilot["client"].get("/api/v1/pilot/history/events", {"action": "tenant.suspended"}).json()
    assert any(e["entity_id"] == a["tenant_id"] for e in audit["results"])


def test_history_persists_across_connections(tenant_user, admin_conn):
    """'Consultation après redémarrage': history is in PostgreSQL, readable from a brand-new connection."""
    a = tenant_user()
    pid = a["client"].post("/api/v1/products", {"name": "R", "slug": "r"}, format="json").json()["id"]
    from django.db import connections
    connections.close_all()  # simulate app restart (all pooled connections dropped)
    n = admin_conn.execute("SELECT count(*) FROM public.entity_history WHERE entity_id = %s", [pid]).fetchone()[0]
    assert n == 1
    assert a["client"].get(f"/api/v1/history/entities/products/{pid}/versions").status_code == 200
