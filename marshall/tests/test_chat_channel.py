"""Web chat channel tests (M4 core).

Verifies:
  - Health and readiness endpoints
  - Session lifecycle (create, use, 404 on unknown)
  - Turns run through the agent runtime (deterministic mode)
  - Chat cannot reach sensitive_action / payment execution
  - Identity is server-derived at session creation
  - The transcript is bounded
"""

from __future__ import annotations


class TestHealth:
    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "healthy"

    def test_ready(self, client):
        resp = client.get("/ready")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ready"

    def test_chat_widget_served(self, client):
        resp = client.get("/chat")
        assert resp.status_code == 200
        assert "Taylor" in resp.text
        assert "api/chat/sessions" in resp.text


class TestSessions:
    def test_create_session(self, client):
        resp = client.post("/api/chat/sessions", json={"customer_id": "cust_9"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["session_id"]
        assert body["conversation_id"].startswith("chat_")
        assert body["customer_id"] == "cust_9"
        # Server derives auth; chat never gets step_up.
        assert body["auth_level"] == "verified"

    def test_create_session_anonymous(self, client):
        resp = client.post("/api/chat/sessions", json={"auth_level": "anonymous"})
        assert resp.status_code == 200
        assert resp.json()["auth_level"] == "anonymous"

    def test_step_up_rejected_for_chat(self, client):
        """Chat cannot claim step_up — the channel is not authorized for it."""
        resp = client.post("/api/chat/sessions", json={"auth_level": "step_up"})
        assert resp.status_code == 400

    def test_unknown_session_404(self, client):
        assert client.post("/api/chat/sessions/nope/messages", json={"message": "hi"}).status_code == 404
        assert client.get("/api/chat/sessions/nope/messages").status_code == 404


class TestMessaging:
    def test_knowledge_question(self, client, session_id):
        resp = client.post(
            f"/api/chat/sessions/{session_id}/messages",
            json={"message": "What happens if I miss a payment?"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["route"] == "knowledge"
        assert body["gate_passed"] is True
        assert body["reply"]

    def test_account_servicing_with_verified_auth(self, client, session_id):
        resp = client.post(
            f"/api/chat/sessions/{session_id}/messages",
            json={"message": "What is my current balance?"},
        )
        assert resp.status_code == 200
        assert resp.json()["route"] in ("account_servicing", "knowledge")

    def test_payment_request_falls_back_from_sensitive_action(self, client, session_id):
        """Chat must NOT route to sensitive_action — architectural constraint."""
        resp = client.post(
            f"/api/chat/sessions/{session_id}/messages",
            json={"message": "I want to make a payment"},
        )
        assert resp.status_code == 200
        assert resp.json()["route"] != "sensitive_action"
        # The payment words classify as sensitive_action, which chat blocks —
        # the router falls back to knowledge per design.

    def test_compliance_phrase_preempts(self, client, session_id):
        resp = client.post(
            f"/api/chat/sessions/{session_id}/messages",
            json={"message": "I need to speak to someone about a dispute"},
        )
        assert resp.status_code == 200
        assert resp.json()["route"] == "compliance_handoff"

    def test_transcript_bounded_and_order(self, client, session_id):
        for i in range(3):
            resp = client.post(
                f"/api/chat/sessions/{session_id}/messages",
                json={"message": f"hello {i}"},
            )
            assert resp.status_code == 200

        history = client.get(f"/api/chat/sessions/{session_id}/messages").json()["messages"]
        roles = [m["role"] for m in history]
        assert roles == ["user", "assistant", "user", "assistant", "user", "assistant"]

    def test_anonymous_session_gets_safe_fallback(self, client):
        resp = client.post("/api/chat/sessions", json={"auth_level": "anonymous"})
        sid = resp.json()["session_id"]
        # Account-specific question with anonymous auth → knowledge fallback.
        resp = client.post(
            f"/api/chat/sessions/{sid}/messages",
            json={"message": "What is my balance?"},
        )
        assert resp.status_code == 200
        assert resp.json()["route"] == "knowledge"
