"""Minimal JWT authentication for local and production-style API boundaries.

This implementation intentionally supports only HS256, which is enough for a
single-service personal project and avoids hiding verification behavior behind
an opaque dependency. Production deployment should use a managed identity
provider or rotate the signing secret through a secret manager.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException

_ALGORITHM = "HS256"
_DEFAULT_ISSUER = "agentic-servicing-platform"


@dataclass(frozen=True)
class Identity:
    subject: str
    customer_id: str
    tenant_id: str
    auth_level: str


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _secret() -> bytes:
    secret = os.environ.get("JWT_SECRET_KEY", "")
    if not secret:
        raise RuntimeError("JWT_SECRET_KEY must be configured")
    return secret.encode("utf-8")


def issue_token(
    customer_id: str,
    auth_level: str = "verified",
    tenant_id: str = "demo",
    *,
    subject: str | None = None,
    ttl_seconds: int = 3_600,
    now: int | None = None,
    secret: bytes | None = None,
) -> str:
    """Issue a compact HS256 token for a demo or trusted identity boundary."""
    if auth_level not in {"anonymous", "verified", "step_up"}:
        raise ValueError("invalid auth_level")
    if not customer_id or not tenant_id:
        raise ValueError("customer_id and tenant_id are required")
    issued_at = int(time.time() if now is None else now)
    header = {"alg": _ALGORITHM, "typ": "JWT"}
    payload = {
        "iss": os.environ.get("JWT_ISSUER", _DEFAULT_ISSUER),
        "sub": subject or customer_id,
        "customer_id": customer_id,
        "tenant_id": tenant_id,
        "auth_level": auth_level,
        "iat": issued_at,
        "exp": issued_at + ttl_seconds,
    }
    encoded_header = _b64encode(json.dumps(header, separators=(",", ":")).encode())
    encoded_payload = _b64encode(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
    signature = hmac.new(secret or _secret(), signing_input, hashlib.sha256).digest()
    return f"{encoded_header}.{encoded_payload}.{_b64encode(signature)}"


def decode_token(
    token: str,
    *,
    now: int | None = None,
    secret: bytes | None = None,
) -> Identity:
    """Verify signature, issuer, expiry, and identity claims."""
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("malformed token")
    encoded_header, encoded_payload, encoded_signature = parts
    try:
        header = json.loads(_b64decode(encoded_header))
        payload = json.loads(_b64decode(encoded_payload))
        signature = _b64decode(encoded_signature)
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("malformed token") from exc

    if header.get("alg") != _ALGORITHM or header.get("typ") != "JWT":
        raise ValueError("unsupported token header")
    signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
    expected = hmac.new(secret or _secret(), signing_input, hashlib.sha256).digest()
    if not hmac.compare_digest(signature, expected):
        raise ValueError("invalid token signature")

    current_time = int(time.time() if now is None else now)
    issuer = os.environ.get("JWT_ISSUER", _DEFAULT_ISSUER)
    if payload.get("iss") != issuer:
        raise ValueError("invalid token issuer")
    if not isinstance(payload.get("exp"), int) or payload["exp"] <= current_time:
        raise ValueError("expired token")
    if not all(
        isinstance(payload.get(field), str) and payload[field]
        for field in ("sub", "customer_id", "tenant_id", "auth_level")
    ):
        raise ValueError("missing identity claims")
    if payload["auth_level"] not in {"anonymous", "verified", "step_up"}:
        raise ValueError("invalid identity claims")
    return Identity(
        subject=payload["sub"],
        customer_id=payload["customer_id"],
        tenant_id=payload["tenant_id"],
        auth_level=payload["auth_level"],
    )


def resolve_identity(
    authorization: str | None,
    *,
    fallback_customer_id: str = "cust_demo_001",
    fallback_auth_level: str = "verified",
    fallback_tenant_id: str = "demo",
) -> Identity:
    """Resolve a bearer identity, or a local-demo identity when allowed."""
    mode = os.environ.get("AUTH_MODE", "demo").lower()
    if authorization is None:
        if mode == "jwt":
            raise HTTPException(status_code=401, detail="Bearer token required")
        return Identity(
            subject=fallback_customer_id,
            customer_id=fallback_customer_id,
            tenant_id=fallback_tenant_id,
            auth_level=fallback_auth_level,
        )

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Bearer token required")
    try:
        return decode_token(token)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Invalid bearer token") from exc


def require_session_access(identity: Identity, session: Any) -> None:
    """Return 404 for cross-tenant access to avoid leaking session existence."""
    if (
        identity.customer_id != session.customer_id
        or identity.tenant_id != session.tenant_id
    ):
        raise HTTPException(status_code=404, detail="session not found")


def enforce_session_access(
    identity: Identity,
    session: Any,
    authorization: str | None,
) -> None:
    """Enforce ownership in JWT mode while preserving the local demo UX."""
    if authorization is None and os.environ.get("AUTH_MODE", "demo").lower() == "demo":
        return
    require_session_access(identity, session)
