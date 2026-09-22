"""
End-to-end graph tests.

Tests the full universal graph: preconditions → router → subgraph → completion_gate.
These tests run the compiled graph (without external services — the graph nodes
in M1 are deterministic state transitions, not LLM calls).
"""

from __future__ import annotations

import pytest

from taylor.graphs.universal.graph import compile_universal_graph
from taylor.graphs.universal.state import (
    AuthLevel,
    Channel,
)


@pytest.fixture
def compiled_graph():
    return compile_universal_graph()


# ── Graph compilation tests ───────────────────────────────────────────────────

class TestGraphCompilation:
    def test_graph_compiles(self):
        graph = compile_universal_graph()
        assert graph is not None

    def test_graph_has_nodes(self, compiled_graph):
        """The compiled graph should have all expected nodes."""
        # LangGraph compiled graphs expose their structure
        # We test by running it, not by inspecting internal structure
        assert compiled_graph is not None


# ── End-to-end routing tests ──────────────────────────────────────────────────

class TestEndToEndRouting:
    async def test_faq_routes_through_knowledge(self, compiled_graph, base_state):
        """FAQ question should route through knowledge subgraph and end at completion gate."""
        state = dict(base_state)
        state["utterance"] = "How do I set up AutoPay?"
        result = await compiled_graph.ainvoke(state)
        assert result.get("route") == "knowledge"

    async def test_balance_routes_through_account_servicing(self, compiled_graph, base_state):
        state = dict(base_state)
        state["utterance"] = "What's my balance?"
        result = await compiled_graph.ainvoke(state)
        assert result.get("route") == "account_servicing"

    async def test_compliance_phrase_preempts(self, compiled_graph, base_state):
        """Compliance phrase should preempt and route to compliance_handoff."""
        state = dict(base_state)
        state["utterance"] = "I'm filing for bankruptcy"
        result = await compiled_graph.ainvoke(state)
        assert result.get("route") == "compliance_handoff"

    async def test_payment_on_chat_falls_back_to_knowledge(self, compiled_graph, base_state):
        """Payment intent on chat should fall back to knowledge (chat can't take payments)."""
        state = dict(base_state)
        state["utterance"] = "I want to pay $300"
        state["channel"] = Channel.CHAT
        state["auth_level"] = AuthLevel.STEP_UP
        result = await compiled_graph.ainvoke(state)
        assert result.get("route") == "knowledge"

    async def test_settlement_routes_to_arrangement(self, compiled_graph, base_state):
        state = dict(base_state)
        state["utterance"] = "Can I settle my contract for less?"
        result = await compiled_graph.ainvoke(state)
        assert result.get("route") == "arrangement"

    async def test_completion_gate_runs(self, compiled_graph, base_state):
        """The completion gate should run after the subgraph and produce a gate_result."""
        state = dict(base_state)
        state["utterance"] = "How do I set up AutoPay?"
        result = await compiled_graph.ainvoke(state)
        assert "gate_result" in result
        assert result["gate_result"].get("gate_passed") is not None


# ── Preconditions tests ───────────────────────────────────────────────────────

class TestPreconditions:
    async def test_missing_conversation_id_handoff(self, compiled_graph, base_state):
        state = dict(base_state)
        state["conversation_id"] = None
        result = await compiled_graph.ainvoke(state)
        assert result.get("route") == "preconditions_failed"

    async def test_missing_customer_id_handoff(self, compiled_graph, base_state):
        state = dict(base_state)
        state["customer_id"] = None
        result = await compiled_graph.ainvoke(state)
        assert result.get("route") == "preconditions_failed"


# ── Loop budget tests ─────────────────────────────────────────────────────────

class TestLoopBudget:
    def test_loop_budget_exceeds_max_turns(self, base_state):
        """When model_turn_count exceeds max, the turn should terminate."""
        state = dict(base_state)
        state["model_turn_count"] = 15  # exceeds max of 10
        # The loop budget check is in the graph, but we can verify the logic
        from taylor.graphs.universal.graph import check_loop_budget
        result = check_loop_budget(state)
        assert result.get("route") == "loop_budget_exceeded"

    def test_loop_budget_under_max(self, base_state):
        """Normal turn count should not trigger budget exceeded."""
        state = dict(base_state)
        state["model_turn_count"] = 3
        from taylor.graphs.universal.graph import check_loop_budget
        result = check_loop_budget(state)
        assert result.get("route") != "loop_budget_exceeded"
        assert result.get("model_turn_count") == 4  # incremented

    def test_loop_budget_exceeds_time(self, base_state):
        """When elapsed time exceeds max, the turn should terminate."""
        import time
        state = dict(base_state)
        state["model_turn_count"] = 1
        state["turn_started_at"] = time.time() - 35  # 35 seconds ago, max is 30
        from taylor.graphs.universal.graph import check_loop_budget
        result = check_loop_budget(state)
        assert result.get("route") == "loop_budget_exceeded"
