"""Login with an e-mail OR a username.

Supabase Auth only authenticates e-mails: the username is resolved server-side (app.login_email, SECURITY
DEFINER, app_backend only) and the password grant is performed by the backend. The e-mail behind a
username is never returned to the browser, and unknown identifiers get exactly the same answer as a wrong
password (no account enumeration). Rate-limited per IP and per identifier.
"""
from __future__ import annotations

import hashlib
import logging
import random
import time

import requests
from django.conf import settings
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, SimpleRateThrottle
from rest_framework.views import APIView

from apps.core.db import fetch_one
from apps.core.exceptions import BusinessError

logger = logging.getLogger("growth.auth")
TOKEN_FIELDS = ("access_token", "refresh_token", "expires_in", "expires_at", "token_type")


class LoginIpThrottle(AnonRateThrottle):
    scope = "login"


class LoginIdentifierThrottle(SimpleRateThrottle):
    """Limits attempts against one account whatever the source IP."""

    scope = "login_identifier"

    def get_cache_key(self, request, view):
        ident = str(request.data.get("identifier", "")).strip().lower() if hasattr(request, "data") else ""
        if not ident:
            return None
        return self.cache_format % {"scope": self.scope, "ident": hashlib.sha256(ident.encode()).hexdigest()}


class UsernameThrottle(AnonRateThrottle):
    scope = "username_check"


def _invalid() -> BusinessError:
    return BusinessError("Identifiant ou mot de passe incorrect.", "invalid_credentials", status_code=401)


def _masked(identifier: str) -> str:
    return identifier[:2] + "***" if identifier else ""


class LoginView(APIView):
    """POST {identifier, password} → Supabase session tokens (the client then calls supabase.auth.setSession)."""

    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes = [LoginIpThrottle, LoginIdentifierThrottle]

    def post(self, request):
        identifier = str(request.data.get("identifier", "")).strip()
        password = str(request.data.get("password", ""))
        if not identifier or not password or len(identifier) > 254 or len(password) > 1024:
            raise _invalid()
        email = fetch_one("SELECT app.login_email(%s)", [identifier])[0]
        if not email:
            time.sleep(random.uniform(0.15, 0.35))  # noqa: S311 — blur the timing difference with a real attempt
            logger.info("login refused (unknown identifier)", extra={"data": {"identifier": _masked(identifier)}})
            raise _invalid()
        try:
            r = requests.post(f"{settings.SUPABASE_URL}/auth/v1/token", params={"grant_type": "password"},
                              json={"email": email, "password": password},
                              headers={"apikey": settings.SUPABASE_ANON_KEY, "Content-Type": "application/json"}, timeout=15)
        except requests.RequestException as e:
            logger.warning("login: Supabase Auth unreachable", extra={"data": {"error": type(e).__name__}})
            raise BusinessError("Le service d'authentification est indisponible. Réessayez.", "auth_unavailable",
                                status_code=503) from e
        if r.status_code == 200:
            body = r.json()
            logger.info("login succeeded", extra={"data": {"identifier": _masked(identifier), "by": "email" if "@" in identifier else "username"}})
            return Response({k: body.get(k) for k in TOKEN_FIELDS})
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        code = body.get("error_code") or body.get("error")
        if code == "email_not_confirmed":
            raise BusinessError("Adresse e-mail non confirmée : utilisez le lien reçu par e-mail.", "email_not_confirmed", status_code=403)
        if r.status_code == 429:
            raise BusinessError("Trop de tentatives. Réessayez dans quelques minutes.", "too_many_attempts", status_code=429)
        if r.status_code >= 500:
            raise BusinessError("Le service d'authentification est indisponible. Réessayez.", "auth_unavailable", status_code=503)
        logger.info("login refused", extra={"data": {"identifier": _masked(identifier), "status": r.status_code}})
        raise _invalid()


class UsernameAvailabilityView(APIView):
    """GET ?username= → {username (normalised), valid, available} — used by the sign-up and profile forms."""

    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes = [UsernameThrottle]

    def get(self, request):
        raw = str(request.query_params.get("username", ""))[:64]
        norm = fetch_one("SELECT app.normalize_username(%s)", [raw])[0]
        if not norm:
            return Response({"username": raw.strip().lower(), "valid": False, "available": False})
        taken = fetch_one("SELECT app.username_taken(%s)", [norm])[0]
        return Response({"username": norm, "valid": True, "available": not taken})
