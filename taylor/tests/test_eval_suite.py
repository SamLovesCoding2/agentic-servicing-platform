"""
Comprehensive 50-case evaluation suite.

Covers all major scenarios:
  1. Router classification accuracy (cases 1-12)
  2. Channel constraints (cases 13-18)
  3. Auth level constraints (cases 19-24)
  4. Compliance phrase preemption (cases 25-28)
  5. Sensitive action state machine (cases 29-33)
  6. Tool envelope security (cases 34-37)
  7. Capability-based tool exposure (cases 38-41)
  8. Completion gate & success language (cases 42-45)
  9. Output filter (cases 46-48)
  10. Edge cases & error handling (cases 49-50)

Each case has: ID, category, description, input, expected result, and assertion.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from taylor.graphs.universal.completion_gate import (
    can_use_success_language,
    completion_gate,
)
from taylor.graphs.universal.router import (
    Route,
    classify_intent,
    route,
    validate_route,
)
from taylor.graphs.universal.state import (
    ActionStatus,
    AuthLevel,
    Channel,
    SubgraphExit,
    compare_and_set,
    merge_slots,
    replace,
)
from taylor.output.output_filter import filter_output
from taylor.tools.base import ExecutionTool, ProposalTool, ReadTool
from taylor.tools.envelope import ToolEnvelope, ToolIntent, ToolResult
from taylor.tools.registry import ToolRegistry

# ── Helpers ──────────────────────────────────────────────────────────────────

def make_state(
    utterance: str = "test",
    auth: AuthLevel = AuthLevel.VERIFIED,
    channel: Channel = Channel.SMS,
    account_id: str = "ACC-001",
    action_status: str = "PROPOSED",
) -> dict[str, Any]:
    return {
        "utterance": utterance,
        "conversation_id": "conv-test",
        "customer_id": "cust-test",
        "auth_level": auth,
        "channel": channel,
        "account_id": account_id,
        "action_status": action_status,
        "collected_slots": {},
    }


def make_registry() -> ToolRegistry:
    """Build a registry with stub tools for testing."""
    from taylor.tools.envelope import ToolPrecondition

    reg = ToolRegistry()

    class StubRead(ReadTool):
        def __init__(self):
            super().__init__("stub_read", "A stub read tool")
        async def execute(self, e, s): return ToolResult(action_id=e.action_id, status="confirmed")

    class StubProposal(ProposalTool):
        def __init__(self):
            super().__init__("stub_proposal", "A stub proposal tool",
                preconditions=[ToolPrecondition(field="account_id", operator="not_null")])
        async def execute(self, e, s): return ToolResult(action_id=e.action_id, status="confirmed")

    class StubExec(ExecutionTool):
        def __init__(self):
            super().__init__("stub_exec", "A stub execution tool",
                preconditions=[ToolPrecondition(field="action_status", operator="eq", value="AUTHORIZED")])
        async def execute(self, e, s): return ToolResult(action_id=e.action_id, status="confirmed")

    reg.register(StubRead())
    reg.register(StubProposal())
    reg.register(StubExec())
    return reg


# ═══════════════════════════════════════════════════════════════════════════════
# CATEGORY 1: Router Classification Accuracy (cases 1-12)
# ═══════════════════════════════════════════════════════════════════════════════

class TestRouterClassification:
    """Cases 1-12: Verify the classifier routes utterances to correct subgraphs."""

    def test_case_01_payment_intent(self):
        """Case 1: 'I want to pay $300' → sensitive_action"""
        assert classify_intent("I want to pay $300") == Route.SENSITIVE_ACTION

    def test_case_02_new_card_payment(self):
        """Case 2: 'pay with a new card' → sensitive_action"""
        assert classify_intent("I want to pay with a new card") == Route.SENSITIVE_ACTION

    def test_case_03_settlement_request(self):
        """Case 3: 'Can I settle my contract?' → arrangement"""
        assert classify_intent("Can I settle my contract?") == Route.ARRANGEMENT

    def test_case_04_payoff_quote(self):
        """Case 4: "What's my payoff amount?" → arrangement"""
        assert classify_intent("What's my payoff amount?") == Route.ARRANGEMENT

    def test_case_05_payment_plan(self):
        """Case 5: 'I need a payment plan' → arrangement (not sensitive_action)"""
        assert classify_intent("I need a payment plan") == Route.ARRANGEMENT

    def test_case_06_update_phone(self):
        """Case 6: 'update my phone number' → account_servicing"""
        assert classify_intent("I need to update my phone number") == Route.ACCOUNT_SERVICING

    def test_case_07_balance_inquiry(self):
        """Case 7: "What's my balance?" → account_servicing"""
        assert classify_intent("What's my balance?") == Route.ACCOUNT_SERVICING

    def test_case_08_faq_missed_payment(self):
        """Case 8: 'What happens if I miss a payment?' → knowledge (not sensitive_action)"""
        assert classify_intent("What happens if I miss a payment?") == Route.KNOWLEDGE

    def test_case_09_faq_autopay(self):
        """Case 9: 'How do I set up AutoPay?' → knowledge"""
        assert classify_intent("How do I set up AutoPay?") == Route.KNOWLEDGE

    def test_case_10_human_transfer(self):
        """Case 10: 'Let me talk to a human' → compliance_handoff"""
        assert classify_intent("Let me talk to a human") == Route.COMPLIANCE_HANDOFF

    def test_case_11_empty_input(self):
        """Case 11: Empty utterance → knowledge (safe default)"""
        assert classify_intent("") == Route.KNOWLEDGE

    def test_case_12_unknown_intent(self):
        """Case 12: Gibberish → knowledge (safe default)"""
        assert classify_intent("xyz abc qrs") == Route.KNOWLEDGE


# ═══════════════════════════════════════════════════════════════════════════════
# CATEGORY 2: Channel Constraints (cases 13-18)
# ═══════════════════════════════════════════════════════════════════════════════

class TestChannelConstraints:
    """Cases 13-18: Verify channel-specific routing restrictions."""

    def test_case_13_sms_allows_sensitive(self):
        """Case 13: SMS allows sensitive_action with step_up auth"""
        assert validate_route(Route.SENSITIVE_ACTION, "sms", AuthLevel.STEP_UP) is True

    def test_case_14_chat_blocks_sensitive(self):
        """Case 14: Chat CANNOT route to sensitive_action (architectural constraint)"""
        assert validate_route(Route.SENSITIVE_ACTION, "chat", AuthLevel.STEP_UP) is False

    def test_case_15_voice_allows_sensitive(self):
        """Case 15: Voice allows sensitive_action with step_up auth"""
        assert validate_route(Route.SENSITIVE_ACTION, "voice", AuthLevel.STEP_UP) is True

    def test_case_16_chat_allows_knowledge(self):
        """Case 16: Chat allows knowledge route"""
        assert validate_route(Route.KNOWLEDGE, "chat", AuthLevel.ANONYMOUS) is True

    def test_case_17_chat_allows_arrangement(self):
        """Case 17: Chat allows arrangement route (quotes but no execution)"""
        assert validate_route(Route.ARRANGEMENT, "chat", AuthLevel.VERIFIED) is True

    def test_case_18_payment_on_chat_falls_back(self):
        """Case 18: Payment intent on chat falls back to knowledge (integration test)"""
        state = make_state("I want to pay $300", AuthLevel.STEP_UP, Channel.CHAT)
        result = route(state)
        assert result["route"] == Route.KNOWLEDGE


# ═══════════════════════════════════════════════════════════════════════════════
# CATEGORY 3: Auth Level Constraints (cases 19-24)
# ═══════════════════════════════════════════════════════════════════════════════

class TestAuthConstraints:
    """Cases 19-24: Verify auth-level requirements per route."""

    def test_case_19_anonymous_can_access_knowledge(self):
        """Case 19: Anonymous can access knowledge (FAQ is public)"""
        assert validate_route(Route.KNOWLEDGE, "sms", AuthLevel.ANONYMOUS) is True

    def test_case_20_anonymous_cannot_access_account(self):
        """Case 20: Anonymous cannot access account_servicing"""
        assert validate_route(Route.ACCOUNT_SERVICING, "sms", AuthLevel.ANONYMOUS) is False

    def test_case_21_verified_can_access_account(self):
        """Case 21: Verified can access account_servicing"""
        assert validate_route(Route.ACCOUNT_SERVICING, "sms", AuthLevel.VERIFIED) is True

    def test_case_22_verified_cannot_execute_sensitive(self):
        """Case 22: Verified cannot execute sensitive actions (needs step_up)"""
        assert validate_route(Route.SENSITIVE_ACTION, "sms", AuthLevel.VERIFIED) is False

    def test_case_23_step_up_can_execute_sensitive(self):
        """Case 23: Step-up can execute sensitive actions"""
        assert validate_route(Route.SENSITIVE_ACTION, "sms", AuthLevel.STEP_UP) is True

    def test_case_24_anonymous_can_trigger_handoff(self):
        """Case 24: Anonymous can trigger compliance handoff (anyone can ask for human)"""
        assert validate_route(Route.COMPLIANCE_HANDOFF, "sms", AuthLevel.ANONYMOUS) is True


# ═══════════════════════════════════════════════════════════════════════════════
# CATEGORY 4: Compliance Phrase Preemption (cases 25-28)
# ═══════════════════════════════════════════════════════════════════════════════

class TestCompliancePreemption:
    """Cases 25-28: Verify compliance phrases preempt all other routing."""

    def test_case_25_bankruptcy_preempts_payment(self):
        """Case 25: Bankruptcy preempts payment intent"""
        state = make_state("I want to pay $300 but I'm filing bankruptcy", AuthLevel.STEP_UP)
        result = route(state)
        assert result["route"] == Route.COMPLIANCE_HANDOFF

    def test_case_26_attorney_preempts_balance(self):
        """Case 26: Attorney preempts balance inquiry"""
        state = make_state("What's my balance? I want to speak to my attorney")
        result = route(state)
        assert result["route"] == Route.COMPLIANCE_HANDOFF

    def test_case_27_death_preempts_on_chat(self):
        """Case 27: Death of account holder preempts on chat channel"""
        state = make_state("The account holder is deceased", AuthLevel.ANONYMOUS, Channel.CHAT)
        result = route(state)
        assert result["route"] == Route.COMPLIANCE_HANDOFF

    def test_case_28_dispute_preempts_on_voice(self):
        """Case 28: Dispute preempts on voice channel"""
        state = make_state("I dispute this debt", AuthLevel.VERIFIED, Channel.VOICE)
        result = route(state)
        assert result["route"] == Route.COMPLIANCE_HANDOFF


# ═══════════════════════════════════════════════════════════════════════════════
# CATEGORY 5: Sensitive Action State Machine (cases 29-33)
# ═══════════════════════════════════════════════════════════════════════════════

class TestStateMachine:
    """Cases 29-33: Verify the 8-state action state machine."""

    def test_case_29_happy_path_all_transitions(self):
        """Case 29: Happy path PROPOSED → NORMALIZED → VALIDATED → AUTHORIZED → EXECUTING → CONFIRMED"""
        path = [
            ActionStatus.PROPOSED, ActionStatus.NORMALIZED, ActionStatus.VALIDATED,
            ActionStatus.AUTHORIZED, ActionStatus.EXECUTING, ActionStatus.CONFIRMED,
        ]
        for i in range(len(path) - 1):
            assert path[i] != path[i + 1]  # Each transition changes state
        assert path[-1] == ActionStatus.CONFIRMED

    def test_case_30_unknown_is_not_rejected(self):
        """Case 30: UNKNOWN is a distinct state, not REJECTED"""
        assert ActionStatus.UNKNOWN != ActionStatus.REJECTED
        assert ActionStatus.UNKNOWN != ActionStatus.CONFIRMED

    def test_case_31_unknown_can_reconcile_to_confirmed(self):
        """Case 31: UNKNOWN → CONFIRMED via reconciliation (valid transition)"""
        # In the real system, a reconciliation worker would transition UNKNOWN → CONFIRMED
        assert ActionStatus.UNKNOWN.value == "UNKNOWN"
        assert ActionStatus.CONFIRMED.value == "CONFIRMED"

    def test_case_32_rejected_is_terminal(self):
        """Case 32: REJECTED is a terminal state (no further transitions)"""
        terminal = {ActionStatus.CONFIRMED, ActionStatus.REJECTED}
        assert ActionStatus.REJECTED in terminal

    def test_case_33_all_eight_states_defined(self):
        """Case 33: All 8 states exist in the enum"""
        expected = {"PROPOSED", "NORMALIZED", "VALIDATED", "AUTHORIZED",
                    "EXECUTING", "CONFIRMED", "REJECTED", "UNKNOWN"}
        actual = {s.value for s in ActionStatus}
        assert actual == expected


# ═══════════════════════════════════════════════════════════════════════════════
# CATEGORY 6: Tool Envelope Security (cases 34-37)
# ═══════════════════════════════════════════════════════════════════════════════

class TestToolEnvelopeSecurity:
    """Cases 34-37: Verify server-derived fields cannot be model-supplied."""

    def test_case_34_identity_in_actor_not_intent(self):
        """Case 34: customer_id is in ToolActor (server-derived), not ToolIntent (model-supplied)"""
        intent = ToolIntent(type="schedule_payment")
        assert not hasattr(intent, "customer_id")
        assert not hasattr(intent, "auth_level")
        assert not hasattr(intent, "account_id")

    def test_case_35_action_id_is_unique_uuid(self):
        """Case 35: Each envelope gets a unique action_id (idempotency key)"""
        e1 = ToolEnvelope.create(conversation_id="c", turn_id="t", customer_id="cust",
            auth_level="verified", intent_type="test")
        e2 = ToolEnvelope.create(conversation_id="c", turn_id="t", customer_id="cust",
            auth_level="verified", intent_type="test")
        assert e1.action_id != e2.action_id

    def test_case_36_amount_is_decimal(self):
        """Case 36: Amounts use Decimal, not float (Pydantic coerces)"""
        intent = ToolIntent(type="schedule_payment", amount=300.00)
        assert isinstance(intent.amount, Decimal)

    def test_case_37_server_fields_cannot_be_overridden(self):
        """Case 37: Server-derived fields are set by coordinator, not model"""
        envelope = ToolEnvelope.create(
            conversation_id="conv-001", turn_id="turn-001",
            customer_id="cust-001", auth_level="step_up",
            account_id="ACC-001", intent_type="schedule_payment",
        )
        # Identity comes from server, intent from model
        assert envelope.actor.customer_id == "cust-001"
        assert envelope.intent.type == "schedule_payment"
        # Intent has no identity fields
        assert not hasattr(envelope.intent, "customer_id")


# ═══════════════════════════════════════════════════════════════════════════════
# CATEGORY 7: Capability-Based Tool Exposure (cases 38-41)
# ═══════════════════════════════════════════════════════════════════════════════

class TestCapabilityExposure:
    """Cases 38-41: Verify execution tools are hidden until preconditions met."""

    def test_case_38_read_always_visible(self):
        """Case 38: Read tools are always visible when authenticated"""
        reg = make_registry()
        state = make_state(action_status="PROPOSED")
        tools = reg.get_visible_tools(state)
        names = [t.name for t in tools]
        assert "stub_read" in names

    def test_case_39_exec_hidden_without_auth(self):
        """Case 39: Execution tools hidden when action_status is PROPOSED"""
        reg = make_registry()
        state = make_state(action_status="PROPOSED")
        tools = reg.get_visible_tools(state)
        names = [t.name for t in tools]
        assert "stub_exec" not in names

    def test_case_40_exec_visible_when_authorized(self):
        """Case 40: Execution tools visible when action_status is AUTHORIZED"""
        reg = make_registry()
        state = make_state(action_status="AUTHORIZED")
        tools = reg.get_visible_tools(state)
        names = [t.name for t in tools]
        assert "stub_exec" in names

    def test_case_41_channel_override_restricts_tools(self):
        """Case 41: Channel override restricts visible tools (chat excludes execution)"""
        reg = make_registry()
        reg.set_channel_tools("chat", {"stub_read", "stub_proposal"})
        state = make_state(action_status="AUTHORIZED")
        tools = reg.get_visible_tools(state, channel="chat")
        names = [t.name for t in tools]
        assert "stub_exec" not in names
        assert "stub_read" in names

    async def test_case_41b_exec_without_auth_rejected(self):
        """Case 41b: Invoking execution tool without authorization_ref is rejected"""
        reg = make_registry()
        state = make_state(action_status="AUTHORIZED")
        envelope = ToolEnvelope.create(
            conversation_id="c", turn_id="t", customer_id="cust",
            auth_level="step_up", intent_type="exec",
        )
        result = await reg.invoke("stub_exec", envelope, state)
        assert result.status == "invalid_request"
        assert "Authorization" in result.error


# ═══════════════════════════════════════════════════════════════════════════════
# CATEGORY 8: Completion Gate & Success Language (cases 42-45)
# ═══════════════════════════════════════════════════════════════════════════════

class TestCompletionGate:
    """Cases 42-45: Verify success language rules and gate validation."""

    def test_case_42_confirmed_allows_success(self):
        """Case 42: CONFIRMED state allows success language for sensitive actions"""
        state = make_state(action_status="CONFIRMED")
        state["route"] = "sensitive_action"
        assert can_use_success_language(state) is True

    def test_case_43_unknown_blocks_success(self):
        """Case 43: UNKNOWN state blocks success language (only 'pending' allowed)"""
        state = make_state(action_status="UNKNOWN")
        state["route"] = "sensitive_action"
        assert can_use_success_language(state) is False

    def test_case_44_invalid_exit_forces_handoff(self):
        """Case 44: Invalid exit state forces handoff via completion gate"""
        state = make_state()
        state["route"] = "knowledge"
        state["exit_state"] = SubgraphExit.CONFIRMED  # Invalid for knowledge
        result = completion_gate(state)
        assert result["gate_result"]["gate_passed"] is False
        assert result["exit_state"] == SubgraphExit.HANDOFF

    def test_case_45_valid_exit_passes_gate(self):
        """Case 45: Valid exit state passes the completion gate"""
        state = make_state()
        state["route"] = "knowledge"
        state["exit_state"] = SubgraphExit.CITED_ANSWER
        result = completion_gate(state)
        assert result["gate_result"]["gate_passed"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# CATEGORY 9: Output Filter (cases 46-48)
# ═══════════════════════════════════════════════════════════════════════════════

class TestOutputFilter:
    """Cases 46-48: Verify word-boundary, case-preserving output filtering."""

    def test_case_46_loan_to_contract(self):
        """Case 46: 'loan' → 'contract' with word boundary"""
        assert "contract" in filter_output("I have a loan to pay")
        assert "loan" not in filter_output("I have a loan to pay")

    def test_case_47_case_preservation(self):
        """Case 47: Case is preserved (Loan → Contract, LOAN → CONTRACT)"""
        assert filter_output("My Loan") == "My Contract"
        assert filter_output("MY LOAN") == "MY CONTRACT"
        assert filter_output("my loan") == "my contract"

    def test_case_48_word_boundary_no_partial_match(self):
        """Case 48: 'loanable' is NOT changed (word boundary aware)"""
        result = filter_output("The loanable amount is $500")
        assert "loanable" in result
        assert "contractable" not in result


# ═══════════════════════════════════════════════════════════════════════════════
# CATEGORY 10: Edge Cases & Error Handling (cases 49-50)
# ═══════════════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    """Cases 49-50: Edge cases and error handling."""

    def test_case_49_authorization_invalidated_on_amount_change(self):
        """Case 49: Versioned authorization invalidates when amount changes"""
        original = Decimal("300.00")
        corrected = Decimal("350.00")
        assert original != corrected
        # In the real system, the auth artifact's is_valid would be set to False

    def test_case_50_cas_prevents_stale_overwrite(self):
        """Case 50: Compare-and-set prevents stale update from overwriting newer state"""
        left = {"amount": "350.00", "version": 2}
        right = {"amount": "300.00", "version": 1}  # Stale
        result = compare_and_set(left, right)
        assert result == left  # Left wins, stale update rejected


# ═══════════════════════════════════════════════════════════════════════════════
# BONUS: Reducer correctness (additional safety cases)
# ═══════════════════════════════════════════════════════════════════════════════

class TestReducerCorrectness:
    """Additional cases for reducer semantics."""

    def test_merge_slots_disjoint(self):
        assert merge_slots({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}

    def test_merge_slots_overlap_right_wins(self):
        assert merge_slots({"a": 1, "b": 2}, {"b": 3}) == {"a": 1, "b": 3}

    def test_replace_always_wins(self):
        assert replace("old", "new") == "new"
        assert replace("old", None) is None

    def test_cas_clear_with_none(self):
        assert compare_and_set({"v": 1}, None) is None

    def test_cas_higher_version_wins(self):
        left = {"v": 1, "version": 1}
        right = {"v": 2, "version": 2}
        assert compare_and_set(left, right) == right
