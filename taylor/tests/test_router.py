"""
Tests for the intent router.

Verifies:
  - Router routes to correct subgraph for given intents
  - Chat channel cannot route to sensitive_action (payment execution)
  - Compliance phrases preempt all other routes
  - Insufficient auth falls back to knowledge
  - Empty utterance defaults to knowledge
"""

from __future__ import annotations

from taylor.graphs.universal.router import (
    Route,
    classify_intent,
    route,
    validate_route,
)
from taylor.graphs.universal.state import AuthLevel, Channel

# ── Classifier tests ──────────────────────────────────────────────────────────

class TestClassifyIntent:
    def test_payment_intent(self):
        assert classify_intent("I want to pay $300") == Route.SENSITIVE_ACTION

    def test_new_card_intent(self):
        assert classify_intent("I want to pay with a new card") == Route.SENSITIVE_ACTION

    def test_settlement_intent(self):
        assert classify_intent("Can I settle my contract?") == Route.ARRANGEMENT

    def test_payoff_intent(self):
        assert classify_intent("What's my payoff amount?") == Route.ARRANGEMENT

    def test_payment_plan_intent(self):
        assert classify_intent("I need a payment plan") == Route.ARRANGEMENT

    def test_update_phone_intent(self):
        assert classify_intent("I need to update my phone number") == Route.ACCOUNT_SERVICING

    def test_balance_intent(self):
        assert classify_intent("What's my balance?") == Route.ACCOUNT_SERVICING

    def test_faq_intent(self):
        assert classify_intent("What happens if I miss a payment?") == Route.KNOWLEDGE

    def test_compliance_phrase(self):
        assert classify_intent("I'm filing for bankruptcy") == Route.COMPLIANCE_HANDOFF

    def test_attorney_phrase(self):
        assert classify_intent("I want to speak to my attorney") == Route.COMPLIANCE_HANDOFF

    def test_transfer_request(self):
        assert classify_intent("Let me talk to a human") == Route.COMPLIANCE_HANDOFF

    def test_empty_utterance(self):
        assert classify_intent("") == Route.KNOWLEDGE

    def test_unknown_intent_defaults_to_knowledge(self):
        assert classify_intent("xyz abc qrs") == Route.KNOWLEDGE


# ── Route validation tests ────────────────────────────────────────────────────

class TestValidateRoute:
    def test_sms_allows_sensitive_action(self):
        assert validate_route(Route.SENSITIVE_ACTION, Channel.SMS.value, AuthLevel.STEP_UP) is True

    def test_chat_blocks_sensitive_action(self):
        """Chat cannot route to sensitive_action — architectural decision."""
        assert validate_route(Route.SENSITIVE_ACTION, Channel.CHAT.value, AuthLevel.STEP_UP) is False

    def test_voice_allows_sensitive_action(self):
        assert validate_route(Route.SENSITIVE_ACTION, Channel.VOICE.value, AuthLevel.STEP_UP) is True

    def test_anonymous_cannot_access_account(self):
        assert validate_route(Route.ACCOUNT_SERVICING, Channel.SMS.value, AuthLevel.ANONYMOUS) is False

    def test_verified_can_access_account(self):
        assert validate_route(Route.ACCOUNT_SERVICING, Channel.SMS.value, AuthLevel.VERIFIED) is True

    def test_verified_cannot_execute_sensitive(self):
        """Sensitive action requires step-up, not just verified."""
        assert validate_route(Route.SENSITIVE_ACTION, Channel.SMS.value, AuthLevel.VERIFIED) is False

    def test_step_up_can_execute_sensitive(self):
        assert validate_route(Route.SENSITIVE_ACTION, Channel.SMS.value, AuthLevel.STEP_UP) is True

    def test_anonymous_can_access_knowledge(self):
        assert validate_route(Route.KNOWLEDGE, Channel.SMS.value, AuthLevel.ANONYMOUS) is True

    def test_anonymous_can_trigger_handoff(self):
        assert validate_route(Route.COMPLIANCE_HANDOFF, Channel.SMS.value, AuthLevel.ANONYMOUS) is True


# ── Router integration tests ──────────────────────────────────────────────────

class TestRouter:
    def test_compliance_phrase_preempts(self, base_state):
        """Compliance phrases should preempt all other routing."""
        state = dict(base_state)
        state["utterance"] = "I want to pay $300 but I'm filing bankruptcy"
        result = route(state)
        assert result["route"] == Route.COMPLIANCE_HANDOFF

    def test_payment_on_chat_falls_back(self, base_state):
        """Payment intent on chat should fall back (chat can't take payments)."""
        state = dict(base_state)
        state["utterance"] = "I want to pay $300"
        state["channel"] = Channel.CHAT
        state["auth_level"] = AuthLevel.STEP_UP
        result = route(state)
        # Should fall back to knowledge since sensitive_action is not allowed on chat
        assert result["route"] == Route.KNOWLEDGE

    def test_payment_on_sms_with_step_up_routes_to_sensitive(self, base_state):
        state = dict(base_state)
        state["utterance"] = "I want to pay $300"
        state["channel"] = Channel.SMS
        state["auth_level"] = AuthLevel.STEP_UP
        result = route(state)
        assert result["route"] == Route.SENSITIVE_ACTION

    def test_payment_on_sms_without_step_up_falls_back(self, base_state):
        """Payment intent without step-up auth should fall back to knowledge."""
        state = dict(base_state)
        state["utterance"] = "I want to pay $300"
        state["channel"] = Channel.SMS
        state["auth_level"] = AuthLevel.VERIFIED
        result = route(state)
        assert result["route"] == Route.KNOWLEDGE

    def test_balance_check_routes_to_account_servicing(self, base_state):
        state = dict(base_state)
        state["utterance"] = "What's my balance?"
        result = route(state)
        assert result["route"] == Route.ACCOUNT_SERVICING

    def test_faq_routes_to_knowledge(self, base_state):
        state = dict(base_state)
        state["utterance"] = "How do I set up AutoPay?"
        result = route(state)
        assert result["route"] == Route.KNOWLEDGE
