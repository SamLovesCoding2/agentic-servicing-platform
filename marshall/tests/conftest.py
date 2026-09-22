"""Marshall test fixtures.

Forces deterministic mode so tests never touch the LLM API or external
mock services, regardless of the developer's local .env.
"""

from __future__ import annotations

import os

os.environ["MARSHALL_LLM_ENABLED"] = "0"  # must be set before importing app

import pytest
from fastapi.testclient import TestClient

from marshall.app.main import app
from marshall.app.sessions import chat_sessions


@pytest.fixture(autouse=True)
def _clean_sessions():
    chat_sessions.clear()
    yield
    chat_sessions.clear()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def session_id(client) -> str:
    resp = client.post("/api/chat/sessions", json={"customer_id": "cust_test_001"})
    assert resp.status_code == 200
    return resp.json()["session_id"]
