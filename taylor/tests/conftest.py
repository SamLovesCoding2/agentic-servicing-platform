"""
Shared test fixtures.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

# Set test environment variables before importing taylor modules
os.environ.setdefault("FAC_API_BASE_URL", "http://localhost:9000")
os.environ.setdefault("PAYMENT_PROVIDER_BASE_URL", "http://localhost:9001")
os.environ.setdefault("OPENAI_API_KEY", "test-key-not-real")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://salient:salient@localhost:5432/salient")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")


@pytest.fixture
def base_state() -> dict[str, Any]:
    """Base graph state for testing."""
    from taylor.graphs.universal.state import AuthLevel, Channel

    return {
        "utterance": "test utterance",
        "conversation_id": "test-conv-001",
        "customer_id": "test-cust-001",
        "auth_level": AuthLevel.VERIFIED,
        "channel": Channel.SMS,
        "account_id": "ACC-001",
        "collected_slots": {},
        "pending_confirmation": None,
        "selected_payment_method": None,
        "action_status": "PROPOSED",
        "action_id": None,
        "action_intent": None,
        "action_result": None,
        "model_turn_count": 0,
        "tool_attempt_counts": {},
    }


@pytest.fixture
def step_up_state(base_state: dict[str, Any]) -> dict[str, Any]:
    """State with step-up auth (required for execution tools)."""
    from taylor.graphs.universal.state import AuthLevel

    state = dict(base_state)
    state["auth_level"] = AuthLevel.STEP_UP
    state["action_status"] = "AUTHORIZED"
    return state
