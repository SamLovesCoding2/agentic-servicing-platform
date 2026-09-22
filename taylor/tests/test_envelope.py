"""
Tests for the tool envelope contract.

Verifies that:
  - Server-derived fields (customer_id, auth_level, account_id) cannot be
    overridden by model input
  - Model-supplied fields are limited to business intent
  - Amounts use Decimal, not float
  - Action ID is a valid idempotency key
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from taylor.tools.envelope import ToolActor, ToolEnvelope, ToolIntent, ToolResult


class TestToolActor:
    def test_valid_actor(self):
        actor = ToolActor(customer_id="cust-001", auth_level="verified", account_id="ACC-001")
        assert actor.customer_id == "cust-001"
        assert actor.auth_level == "verified"
        assert actor.account_id == "ACC-001"

    def test_account_id_optional(self):
        actor = ToolActor(customer_id="cust-001", auth_level="anonymous")
        assert actor.account_id is None

    def test_requires_step_up(self):
        actor = ToolActor(customer_id="cust-001", auth_level="verified")
        assert actor.requires_step_up() is True

        actor_step_up = ToolActor(customer_id="cust-001", auth_level="step_up")
        assert actor_step_up.requires_step_up() is False


class TestToolIntent:
    def test_valid_intent(self):
        intent = ToolIntent(type="schedule_payment", amount=Decimal("300.00"), date=date(2026, 9, 15))
        assert intent.type == "schedule_payment"
        assert intent.amount == Decimal("300.00")

    def test_amount_must_be_decimal_not_float(self):
        """Amounts use Decimal, not binary floating point. Pydantic coerces
        float to Decimal on validation, so we verify the stored type."""
        intent = ToolIntent(type="schedule_payment", amount=300.00)
        # Pydantic v2 coerces float → Decimal, so the stored value should be Decimal
        assert isinstance(intent.amount, Decimal)
        assert intent.amount == Decimal("300.0")

    def test_amount_decimal_precision_preserved(self):
        """Decimal precision is preserved (float would lose this)."""
        intent = ToolIntent(type="schedule_payment", amount=Decimal("300.00"))
        assert intent.amount == Decimal("300.00")

    def test_extra_fields_allowed(self):
        intent = ToolIntent(type="update_phone", extra={"phone": "+15551234567"})
        assert intent.extra["phone"] == "+15551234567"

    def test_no_customer_id_in_intent(self):
        """The model cannot supply customer_id — it's not in the intent schema."""
        intent = ToolIntent(type="schedule_payment")
        assert not hasattr(intent, "customer_id")
        assert not hasattr(intent, "auth_level")
        assert not hasattr(intent, "account_id")


class TestToolEnvelope:
    def test_create_envelope(self):
        envelope = ToolEnvelope.create(
            conversation_id="conv-001",
            turn_id="turn-001",
            customer_id="cust-001",
            auth_level="step_up",
            account_id="ACC-001",
            intent_type="schedule_payment",
            amount="300.00",
            date_value=date(2026, 9, 15),
            method_token="pm_tok_001",
        )
        assert envelope.conversation_id == "conv-001"
        assert envelope.actor.customer_id == "cust-001"
        assert envelope.actor.auth_level == "step_up"
        assert envelope.intent.amount == Decimal("300.00")
        assert envelope.intent.method_token == "pm_tok_001"

    def test_action_id_is_unique(self):
        """Each envelope gets a unique action_id (idempotency key)."""
        e1 = ToolEnvelope.create(
            conversation_id="c", turn_id="t", customer_id="cust",
            auth_level="verified", intent_type="test",
        )
        e2 = ToolEnvelope.create(
            conversation_id="c", turn_id="t", customer_id="cust",
            auth_level="verified", intent_type="test",
        )
        assert e1.action_id != e2.action_id

    def test_action_id_is_valid_uuid(self):
        envelope = ToolEnvelope.create(
            conversation_id="c", turn_id="t", customer_id="cust",
            auth_level="verified", intent_type="test",
        )
        # Should be a valid UUID string
        UUID(envelope.action_id)

    def test_server_derived_fields_separate_from_model(self):
        """Server-derived fields are in the envelope/actor, not the intent.
        The model can only populate the intent."""
        envelope = ToolEnvelope.create(
            conversation_id="conv-001",
            turn_id="turn-001",
            customer_id="cust-001",
            auth_level="verified",
            account_id="ACC-001",
            intent_type="schedule_payment",
        )
        # Identity is in actor (server-derived)
        assert envelope.actor.customer_id == "cust-001"
        # Intent has no identity fields
        assert not hasattr(envelope.intent, "customer_id")
        assert not hasattr(envelope.intent, "auth_level")


class TestToolResult:
    def test_success(self):
        result = ToolResult(action_id="act-001", status="confirmed")
        assert result.is_success is True
        assert result.is_unknown is False

    def test_unknown(self):
        result = ToolResult(action_id="act-001", status="unknown")
        assert result.is_success is False
        assert result.is_unknown is True

    def test_rejected(self):
        result = ToolResult(action_id="act-001", status="rejected", error="Insufficient funds")
        assert result.is_success is False
        assert result.is_unknown is False
        assert result.error == "Insufficient funds"

    def test_with_confirmation(self):
        result = ToolResult(
            action_id="act-001",
            status="confirmed",
            confirmation_id="CONF-12345",
            provider_request_id="PR-abcdef",
        )
        assert result.confirmation_id == "CONF-12345"
        assert result.provider_request_id == "PR-abcdef"
