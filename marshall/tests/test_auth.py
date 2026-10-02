from __future__ import annotations

from marshall.app.auth import decode_token, issue_token


def test_jwt_round_trip_and_claims(monkeypatch):
    monkeypatch.setenv("JWT_ISSUER", "test-issuer")
    token = issue_token(
        customer_id="cust-1",
        tenant_id="tenant-a",
        auth_level="verified",
        secret=b"test-secret",
        now=1_000,
    )

    identity = decode_token(token, secret=b"test-secret", now=1_001)

    assert identity.customer_id == "cust-1"
    assert identity.tenant_id == "tenant-a"
    assert identity.auth_level == "verified"


def test_expired_and_tampered_tokens_are_rejected(monkeypatch):
    monkeypatch.setenv("JWT_ISSUER", "test-issuer")
    token = issue_token(
        customer_id="cust-1",
        secret=b"test-secret",
        ttl_seconds=10,
        now=1_000,
    )

    try:
        decode_token(token, secret=b"test-secret", now=1_010)
    except ValueError as exc:
        assert str(exc) == "expired token"
    else:
        raise AssertionError("expired token was accepted")

    header, payload, signature = token.split(".")
    replacement = "a" if signature[-1] != "a" else "b"
    tampered = f"{header}.{payload}.{signature[:-1]}{replacement}"
    try:
        decode_token(tampered, secret=b"test-secret", now=1_001)
    except ValueError as exc:
        assert str(exc) == "invalid token signature"
    else:
        raise AssertionError("tampered token was accepted")


def test_jwt_mode_requires_bearer_token(client, monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "jwt")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret")

    response = client.post("/api/chat/sessions", json={})

    assert response.status_code == 401
    assert response.json()["detail"] == "Bearer token required"


def test_jwt_mode_enforces_tenant_and_customer_isolation(client, monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "jwt")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret")
    owner_token = issue_token(
        customer_id="cust-owner",
        tenant_id="tenant-a",
        secret=b"test-secret",
    )
    other_token = issue_token(
        customer_id="cust-other",
        tenant_id="tenant-a",
        secret=b"test-secret",
    )

    response = client.post(
        "/api/chat/sessions",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={},
    )
    session_id = response.json()["session_id"]

    response = client.post(
        f"/api/chat/sessions/{session_id}/messages",
        headers={"Authorization": f"Bearer {other_token}"},
        json={"message": "hello"},
    )

    assert response.status_code == 404


def test_demo_token_endpoint_is_local_only(client, monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "demo")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret")

    response = client.post(
        "/api/auth/demo-token",
        json={"customer_id": "cust-demo", "tenant_id": "tenant-demo"},
    )

    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"
    assert decode_token(response.json()["access_token"], secret=b"test-secret").customer_id == "cust-demo"


def test_demo_token_endpoint_disabled_in_jwt_mode(client, monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "jwt")

    response = client.post("/api/auth/demo-token", json={})

    assert response.status_code == 404
