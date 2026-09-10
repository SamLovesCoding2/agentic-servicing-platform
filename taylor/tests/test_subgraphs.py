"""
Tests for subgraph contracts.

Verifies:
  - Each subgraph returns only its declared exit states
  - Subgraph contracts are properly defined
  - The completion gate validates exit states correctly
"""

from __future__ import annotations

import pytest

from taylor.graphs.universal.completion_gate import (
    SUBGRAPH_VALID_EXITS,
    can_use_success_language,
    completion_gate,
    validate_exit,
)
from taylor.graphs.universal.state import ActionStatus, SubgraphExit
from taylor.graphs.subgraphs.knowledge import KNOWLEDGE_CONTRACT
from taylor.graphs.subgraphs.account_servicing import ACCOUNT_SERVICING_CONTRACT
from taylor.graphs.subgraphs.arrangement import ARRANGEMENT_CONTRACT
from taylor.graphs.subgraphs.sensitive_action import SENSITIVE_ACTION_CONTRACT
from taylor.graphs.subgraphs.compliance_handoff import COMPLIANCE_HANDOFF_CONTRACT


# ── Contract definition tests ─────────────────────────────────────────────────

class TestContractDefinitions:
    def test_knowledge_contract(self):
        assert KNOWLEDGE_CONTRACT["name"] == "knowledge"
        assert SubgraphExit.CITED_ANSWER in KNOWLEDGE_CONTRACT["required_exits"]
        assert SubgraphExit.NO_ANSWER in KNOWLEDGE_CONTRACT["required_exits"]
        assert "read" in KNOWLEDGE_CONTRACT["tool_authority"]

    def test_account_servicing_contract(self):
        assert ACCOUNT_SERVICING_CONTRACT["name"] == "account_servicing"
        assert SubgraphExit.FRESH_RESULT in ACCOUNT_SERVICING_CONTRACT["required_exits"]
        assert SubgraphExit.PRECONDITION_REJECTED in ACCOUNT_SERVICING_CONTRACT["required_exits"]

    def test_arrangement_contract(self):
        assert ARRANGEMENT_CONTRACT["name"] == "arrangement"
        assert SubgraphExit.VALIDATED_PROPOSAL in ARRANGEMENT_CONTRACT["required_exits"]
        assert SubgraphExit.INVALID_PROPOSAL in ARRANGEMENT_CONTRACT["required_exits"]
        assert "proposal" in ARRANGEMENT_CONTRACT["tool_authority"]
        # Arrangement should NOT have execution authority
        assert "execution" not in ARRANGEMENT_CONTRACT["tool_authority"]

    def test_sensitive_action_contract(self):
        assert SENSITIVE_ACTION_CONTRACT["name"] == "sensitive_action"
        assert SubgraphExit.CONFIRMED in SENSITIVE_ACTION_CONTRACT["required_exits"]
        assert SubgraphExit.UNKNOWN_RECONCILING in SENSITIVE_ACTION_CONTRACT["required_exits"]
        assert "execution" in SENSITIVE_ACTION_CONTRACT["tool_authority"]

    def test_compliance_handoff_contract(self):
        assert COMPLIANCE_HANDOFF_CONTRACT["name"] == "compliance_handoff"
        assert SubgraphExit.POLICY_DENY in COMPLIANCE_HANDOFF_CONTRACT["required_exits"]
        assert SubgraphExit.TRANSFER_ACCEPTED in COMPLIANCE_HANDOFF_CONTRACT["required_exits"]


# ── Exit state validation tests ───────────────────────────────────────────────

class TestExitValidation:
    def test_valid_knowledge_exit(self):
        assert validate_exit("knowledge", SubgraphExit.CITED_ANSWER) is True
        assert validate_exit("knowledge", SubgraphExit.NO_ANSWER) is True

    def test_invalid_knowledge_exit(self):
        """Knowledge subgraph cannot return CONFIRMED — that's a sensitive_action exit."""
        assert validate_exit("knowledge", SubgraphExit.CONFIRMED) is False

    def test_valid_sensitive_action_exit(self):
        for exit_state in [SubgraphExit.CONFIRMED, SubgraphExit.REJECTED,
                           SubgraphExit.CANCELLED, SubgraphExit.UNKNOWN_RECONCILING]:
            assert validate_exit("sensitive_action", exit_state) is True

    def test_invalid_sensitive_action_exit(self):
        """Sensitive action cannot return CITED_ANSWER — that's a knowledge exit."""
        assert validate_exit("sensitive_action", SubgraphExit.CITED_ANSWER) is False

    def test_none_exit_is_invalid(self):
        assert validate_exit("knowledge", None) is False

    def test_string_exit_normalized(self):
        """String exit states should be normalized to SubgraphExit."""
        assert validate_exit("knowledge", "cited_answer") is True
        assert validate_exit("knowledge", "no_answer") is True

    def test_invalid_string_exit(self):
        assert validate_exit("knowledge", "nonexistent_exit") is False


# ── Success language tests ────────────────────────────────────────────────────

class TestSuccessLanguage:
    def test_confirmed_sensitive_action_allows_success(self, base_state):
        state = dict(base_state)
        state["route"] = "sensitive_action"
        state["action_status"] = ActionStatus.CONFIRMED
        assert can_use_success_language(state) is True

    def test_unknown_sensitive_action_blocks_success(self, base_state):
        """UNKNOWN state must NOT allow success language — only 'pending' language."""
        state = dict(base_state)
        state["route"] = "sensitive_action"
        state["action_status"] = ActionStatus.UNKNOWN
        assert can_use_success_language(state) is False

    def test_executing_sensitive_action_blocks_success(self, base_state):
        """EXECUTING is not yet confirmed — no success language."""
        state = dict(base_state)
        state["route"] = "sensitive_action"
        state["action_status"] = ActionStatus.EXECUTING
        assert can_use_success_language(state) is False

    def test_rejected_sensitive_action_blocks_success(self, base_state):
        state = dict(base_state)
        state["route"] = "sensitive_action"
        state["action_status"] = ActionStatus.REJECTED
        assert can_use_success_language(state) is False

    def test_knowledge_cited_answer_allows_success(self, base_state):
        state = dict(base_state)
        state["route"] = "knowledge"
        state["exit_state"] = SubgraphExit.CITED_ANSWER
        assert can_use_success_language(state) is True

    def test_knowledge_no_answer_blocks_success(self, base_state):
        state = dict(base_state)
        state["route"] = "knowledge"
        state["exit_state"] = SubgraphExit.NO_ANSWER
        assert can_use_success_language(state) is False


# ── Completion gate tests ─────────────────────────────────────────────────────

class TestCompletionGate:
    def test_gate_passes_with_valid_exit(self, base_state):
        state = dict(base_state)
        state["route"] = "knowledge"
        state["exit_state"] = SubgraphExit.CITED_ANSWER
        result = completion_gate(state)
        assert result["gate_result"]["gate_passed"] is True

    def test_gate_fails_with_invalid_exit(self, base_state):
        state = dict(base_state)
        state["route"] = "knowledge"
        state["exit_state"] = SubgraphExit.CONFIRMED  # Invalid for knowledge
        result = completion_gate(state)
        assert result["gate_result"]["gate_passed"] is False
        # Should force handoff on invalid exit
        assert result["exit_state"] == SubgraphExit.HANDOFF

    def test_gate_blocks_success_for_unknown(self, base_state):
        state = dict(base_state)
        state["route"] = "sensitive_action"
        state["action_status"] = ActionStatus.UNKNOWN
        state["exit_state"] = SubgraphExit.UNKNOWN_RECONCILING
        result = completion_gate(state)
        assert result["gate_result"]["success_language_allowed"] is False

    def test_gate_allows_success_for_confirmed(self, base_state):
        state = dict(base_state)
        state["route"] = "sensitive_action"
        state["action_status"] = ActionStatus.CONFIRMED
        state["exit_state"] = SubgraphExit.CONFIRMED
        result = completion_gate(state)
        assert result["gate_result"]["success_language_allowed"] is True
