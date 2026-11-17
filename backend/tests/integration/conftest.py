"""Integration fixtures: real PostgreSQL prepared by infrastructure/scripts/db_local.sh (Supabase emulation +
all SQL migrations). Django connects as app_backend (RLS enforced). Users are created through an admin
connection, exactly like Supabase Auth would."""
import os
import time
import uuid

import jwt
import psycopg
import pytest
from rest_framework.test import APIClient


@pytest.fixture(scope="session")
def django_db_setup():
    """Use the prepared database as-is (no test DB re-creation)."""


@pytest.fixture
def admin_conn():
    with psycopg.connect(os.environ["DB_ADMIN_URL"], autocommit=True) as conn:
        yield conn


def make_token(user_id: str, email: str, aal: str = "aal1") -> str:
    from django.conf import settings
    now = int(time.time())
    return jwt.encode({"sub": user_id, "email": email, "role": "authenticated", "aud": "authenticated", "aal": aal,
                       "iss": f"{settings.SUPABASE_URL}/auth/v1", "iat": now, "exp": now + 600,
                       "user_metadata": {"email_verified": True}}, settings.SUPABASE_JWT_SECRET, algorithm="HS256")


@pytest.fixture
def make_user(admin_conn):
    def _make(verified=True, pilot=False):
        uid, email = str(uuid.uuid4()), f"it-{uuid.uuid4().hex[:10]}@example.test"
        admin_conn.execute("INSERT INTO auth.users (id, email, email_confirmed_at) VALUES (%s, %s, %s)",
                           [uid, email, "now()" if verified else None])
        if pilot:
            admin_conn.execute("INSERT INTO public.user_profiles (id, email, platform_role_code) VALUES (%s, %s, 'PILOTE')", [uid, email])
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION="Bearer " + make_token(uid, email, "aal2" if pilot else "aal1"))
        return {"id": uid, "email": email, "client": client}
    return _make


@pytest.fixture
def tenant_user(make_user):
    """A verified user with a provisioned DEMO tenant."""
    def _make():
        u = make_user()
        r = u["client"].post("/api/v1/signup/demo", {"tenant_name": "IT", "slug": "it-" + uuid.uuid4().hex[:10]}, format="json")
        assert r.status_code == 201, r.content
        u["tenant_id"] = r.json()["tenant_id"]
        u["client"].credentials(HTTP_AUTHORIZATION=u["client"]._credentials["HTTP_AUTHORIZATION"], HTTP_X_TENANT_ID=u["tenant_id"])
        return u
    return _make
