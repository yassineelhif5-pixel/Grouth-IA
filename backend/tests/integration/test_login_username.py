"""Login by e-mail OR username: resolution server-side, no e-mail leak, no account enumeration, uniqueness."""
import json
import uuid

import pytest
import responses
from django.conf import settings
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db(transaction=True, databases=["default", "logs"])
TOKENS = {"access_token": "at", "refresh_token": "rt", "expires_in": 3600, "expires_at": 1, "token_type": "bearer",
          "user": {"email": "should-not-leak@example.test"}}


@pytest.fixture
def supabase_auth():
    with responses.RequestsMock(assert_all_requests_are_fired=False) as r:
        r.add_passthru("http://127.0.0.1")
        yield r


def token_url():
    return f"{settings.SUPABASE_URL}/auth/v1/token"


def anon():
    return APIClient(REMOTE_ADDR=f"10.0.{uuid.uuid4().int % 250}.{uuid.uuid4().int % 250}")


def test_username_set_then_login_by_username_or_email(tenant_user, supabase_auth):
    a = tenant_user()
    name = "user_" + uuid.uuid4().hex[:8]
    r = a["client"].patch("/api/v1/me", {"username": name.upper()}, format="json")
    assert r.status_code == 200, r.content
    assert r.json()["username"] == name  # stored normalised
    assert a["client"].get("/api/v1/me").json()["profile"]["username"] == name

    supabase_auth.add(responses.POST, token_url(), json=TOKENS, status=200)
    res = anon().post("/api/v1/auth/login", {"identifier": name.capitalize(), "password": "Secret-password-1"}, format="json")
    assert res.status_code == 200, res.content
    assert res.json() == {k: TOKENS[k] for k in ("access_token", "refresh_token", "expires_in", "expires_at", "token_type")}
    sent = json.loads(supabase_auth.calls[-1].request.body)
    assert sent == {"email": a["email"], "password": "Secret-password-1"}  # username resolved to the account e-mail
    assert a["email"] not in res.content.decode()  # e-mail never returned to the browser

    res = anon().post("/api/v1/auth/login", {"identifier": a["email"].upper(), "password": "Secret-password-1"}, format="json")
    assert res.status_code == 200
    assert json.loads(supabase_auth.calls[-1].request.body)["email"] == a["email"]


def test_unknown_username_and_wrong_password_look_identical(tenant_user, supabase_auth):
    a = tenant_user()
    name = "known_" + uuid.uuid4().hex[:8]
    assert a["client"].patch("/api/v1/me", {"username": name}, format="json").status_code == 200
    supabase_auth.add(responses.POST, token_url(), json={"error": "invalid_grant", "error_code": "invalid_credentials"}, status=400)

    unknown = anon().post("/api/v1/auth/login", {"identifier": "nobody_" + uuid.uuid4().hex[:6], "password": "x" * 12}, format="json")
    calls_after_unknown = len(supabase_auth.calls)
    wrong = anon().post("/api/v1/auth/login", {"identifier": name, "password": "wrong-password"}, format="json")
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["error"]["code"] == wrong.json()["error"]["code"] == "invalid_credentials"
    assert unknown.json()["error"]["message"] == wrong.json()["error"]["message"]
    assert calls_after_unknown == 0  # unknown username: Supabase is never called with a guessed e-mail


def test_unconfirmed_email_and_provider_outage(tenant_user, supabase_auth):
    a = tenant_user()
    supabase_auth.add(responses.POST, token_url(), json={"error_code": "email_not_confirmed"}, status=400)
    r = anon().post("/api/v1/auth/login", {"identifier": a["email"], "password": "Secret-password-1"}, format="json")
    assert r.status_code == 403 and r.json()["error"]["code"] == "email_not_confirmed"
    supabase_auth.replace(responses.POST, token_url(), body=responses.ConnectionError("down"))
    r = anon().post("/api/v1/auth/login", {"identifier": a["email"], "password": "Secret-password-1"}, format="json")
    assert r.status_code == 503 and r.json()["error"]["code"] == "auth_unavailable"


def test_username_uniqueness_format_and_availability(tenant_user):
    a, b = tenant_user(), tenant_user()
    name = "dup_" + uuid.uuid4().hex[:8]
    assert a["client"].patch("/api/v1/me", {"username": name}, format="json").status_code == 200
    r = b["client"].patch("/api/v1/me", {"username": name.upper()}, format="json")
    assert r.status_code == 409 and r.json()["error"]["code"] == "username_taken"
    r = b["client"].patch("/api/v1/me", {"username": "bad name@x"}, format="json")
    assert r.status_code == 400

    avail = anon().get("/api/v1/auth/username-available", {"username": name.upper()}).json()
    assert avail == {"username": name, "valid": True, "available": False}
    free = "free_" + uuid.uuid4().hex[:8]
    assert anon().get("/api/v1/auth/username-available", {"username": free}).json() == {"username": free, "valid": True, "available": True}
    assert anon().get("/api/v1/auth/username-available", {"username": "a b"}).json()["valid"] is False


def test_login_is_rate_limited_per_identifier(supabase_auth):
    supabase_auth.add(responses.POST, token_url(), json={"error_code": "invalid_credentials"}, status=400)
    ident = "victim_" + uuid.uuid4().hex[:8]
    codes = [anon().post("/api/v1/auth/login", {"identifier": ident, "password": "x" * 12}, format="json").status_code for _ in range(7)]
    assert codes[:5] == [401] * 5 and codes[-1] == 429  # 5/min per account, whatever the source IP
