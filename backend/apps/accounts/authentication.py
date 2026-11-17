"""Supabase Auth JWT validation (cryptographic signature + claims).

Supports asymmetric signing keys via the project JWKS endpoint (ES256/RS256, recommended)
and the legacy shared HS256 secret. Checks exp/iat/nbf, audience, issuer and subject.
"""
from __future__ import annotations

import functools
from dataclasses import dataclass, field

import jwt
from django.conf import settings
from rest_framework import authentication, exceptions

from apps.core.context import parse_uuid


@dataclass(frozen=True)
class SupabaseUser:
    id: str
    email: str | None
    role: str
    aal: str = "aal1"
    email_verified: bool = False
    claims: dict = field(default_factory=dict, repr=False)
    is_authenticated: bool = True
    is_anonymous: bool = False

    @property
    def pk(self) -> str:
        return self.id


@functools.lru_cache(maxsize=1)
def _jwks_client() -> jwt.PyJWKClient:
    return jwt.PyJWKClient(f"{settings.SUPABASE_URL}/auth/v1/.well-known/jwks.json", cache_keys=True, lifespan=600)


def decode_supabase_jwt(token: str) -> dict:
    header = jwt.get_unverified_header(token)
    alg = header.get("alg")
    issuer = f"{settings.SUPABASE_URL}/auth/v1"
    options = {"require": ["exp", "iat", "sub", "aud", "iss"]}
    if alg == "HS256":
        if not settings.SUPABASE_JWT_SECRET:
            raise exceptions.AuthenticationFailed("HS256 tokens not accepted (no shared secret configured)")
        key = settings.SUPABASE_JWT_SECRET
    elif alg in ("ES256", "RS256", "EdDSA"):
        key = _jwks_client().get_signing_key_from_jwt(token).key
    else:
        raise exceptions.AuthenticationFailed("Unsupported JWT algorithm")
    return jwt.decode(token, key, algorithms=[alg], audience=settings.SUPABASE_JWT_AUDIENCE, issuer=issuer,
                      options=options, leeway=30)


def user_from_claims(claims: dict) -> SupabaseUser:
    sub = parse_uuid(claims.get("sub"))
    if not sub or claims.get("role") != "authenticated":
        raise exceptions.AuthenticationFailed("Invalid subject or role")
    meta = claims.get("user_metadata") or {}
    verified = bool(meta.get("email_verified")) or bool(claims.get("email_verified"))
    return SupabaseUser(id=sub, email=claims.get("email"), role=claims["role"], aal=claims.get("aal", "aal1"),
                        email_verified=verified, claims=claims)


class SupabaseJWTAuthentication(authentication.BaseAuthentication):
    keyword = "Bearer"

    def authenticate(self, request):
        header = authentication.get_authorization_header(request).decode()
        if not header:
            return None
        parts = header.split()
        if len(parts) != 2 or parts[0] != self.keyword:
            raise exceptions.AuthenticationFailed("Invalid Authorization header")
        try:
            claims = decode_supabase_jwt(parts[1])
        except jwt.ExpiredSignatureError as e:
            raise exceptions.AuthenticationFailed("Token expired") from e
        except jwt.PyJWTError as e:
            raise exceptions.AuthenticationFailed("Invalid token") from e
        return user_from_claims(claims), claims

    def authenticate_header(self, request):
        return self.keyword
