"""Synthetic IdP for the OIDC tests: a throw-away RSA key, its JWKS and signed tokens (no network, no secret)."""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass, field
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

ISSUER = "https://idp.orion.test/realms/orion"
JWKS_URL = f"{ISSUER}/protocol/openid-connect/certs"
TOKEN_URL = f"{ISSUER}/protocol/openid-connect/token"
AUTH_URL = f"{ISSUER}/protocol/openid-connect/auth"
REDIRECT_URI = "http://testserver/api/v1/auth/oidc/callback"


def _b64(number: int) -> str:
    raw = number.to_bytes((number.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


@dataclass
class IdpKey:
    kid: str
    private: rsa.RSAPrivateKey = field(default_factory=lambda: rsa.generate_private_key(65537, 2048))

    @property
    def jwk(self) -> dict[str, str]:
        numbers = self.private.public_key().public_numbers()
        return {
            "kty": "RSA",
            "use": "sig",
            "alg": "RS256",
            "kid": self.kid,
            "n": _b64(numbers.n),
            "e": _b64(numbers.e),
        }

    def sign(self, claims: dict[str, Any], *, kid: str | None = None) -> str:
        pem = self.private.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
        return jwt.encode(claims, pem, algorithm="RS256", headers={"kid": kid or self.kid})


KEY = IdpKey("test-key-1")
ROTATED_KEY = IdpKey("test-key-2")


def jwks(*keys: IdpKey) -> dict[str, Any]:
    return {"keys": [k.jwk for k in keys]}


def claims(subject: str, **overrides: Any) -> dict[str, Any]:
    """A valid FORGE access-token payload (synthetic identity); ``None`` removes a claim."""
    now = int(time.time())
    base: dict[str, Any] = {
        "iss": ISSUER,
        "sub": subject,
        "aud": "forge",
        "iat": now - 5,
        "exp": now + 300,
        "email": "someone@example.test",
        "email_verified": True,
        "name": "Une Personne",
        "orion_workspace_id": "00000000-0000-4000-8000-000000000001",
        "amr": ["pwd"],
    }
    base.update(overrides)
    return {k: v for k, v in base.items() if v is not None}


def token(subject: str, key: IdpKey = KEY, *, kid: str | None = None, **overrides: Any) -> str:
    return key.sign(claims(subject, **overrides), kid=kid)
