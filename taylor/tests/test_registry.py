"""
Tests for the tool registry and capability-based exposure.

Verifies:
  - Read tools are always visible (once authenticated)
  - Proposal tools are visible only when preconditions are met
  - Execution tools are HIDDEN until preconditions are met
  - Channel overrides restrict the tool surface
  - Authorization is required for execution tool invocation
  - Unknown tools are rejected
  - Precondition violations are rejected
"""

from __future__ import annotations

import pytest

from taylor.tools.base import ExecutionTool, ProposalTool, ReadTool
from taylor.tools.envelope import ToolEnvelope, ToolPrecondition
from taylor.tools.registry import ToolRegistry

# ── Stub tools for testing ────────────────────────────────────────────────────

class StubReadTool(ReadTool):
    def __init__(self):
        super().__init__("stub_read", "A stub read tool")

    async def execute(self, envelope, state):
        from taylor.tools.envelope import ToolResult
        return ToolResult(action_id=envelope.action_id, status="confirmed", data={"read": True})


class StubProposalTool(ProposalTool):
    def __init__(self):
        super().__init__(
            "stub_proposal", "A stub proposal tool",
            preconditions=[ToolPrecondition(field="account_id", operator="not_null")],
        )

    async def execute(self, envelope, state):
        from taylor.tools.envelope import ToolResult
        return ToolResult(action_id=envelope.action_id, status="confirmed", data={"proposal": True})


class StubExecutionTool(ExecutionTool):
    def __init__(self):
        super().__init__(
            "stub_execution", "A stub execution tool",
            preconditions=[ToolPrecondition(field="action_status", operator="eq", value="AUTHORIZED")],
        )

    async def execute(self, envelope, state):
        from taylor.tools.envelope import ToolResult
        return ToolResult(action_id=envelope.action_id, status="confirmed", data={"executed": True})


@pytest.fixture
def registry():
    reg = ToolRegistry()
    reg.register(StubReadTool())
    reg.register(StubProposalTool())
    reg.register(StubExecutionTool())
    return reg


# ── Visibility tests ──────────────────────────────────────────────────────────

class TestToolVisibility:
    def test_read_tool_always_visible(self, registry, base_state):
        tools = registry.get_visible_tools(base_state)
        names = [t.name for t in tools]
        assert "stub_read" in names

    def test_proposal_hidden_without_account_id(self, registry, base_state):
        """Proposal tool requires account_id — hidden without it."""
        state = dict(base_state)
        state["account_id"] = None
        tools = registry.get_visible_tools(state)
        names = [t.name for t in tools]
        assert "stub_proposal" not in names

    def test_proposal_visible_with_account_id(self, registry, base_state):
        state = dict(base_state)
        state["account_id"] = "ACC-001"
        tools = registry.get_visible_tools(state)
        names = [t.name for t in tools]
        assert "stub_proposal" in names

    def test_execution_hidden_without_authorization(self, registry, base_state):
        """Execution tool requires action_status=AUTHORIZED — hidden without it."""
        state = dict(base_state)
        state["action_status"] = "PROPOSED"
        tools = registry.get_visible_tools(state)
        names = [t.name for t in tools]
        assert "stub_execution" not in names

    def test_execution_visible_with_authorization(self, registry, step_up_state):
        """Execution tool visible when action_status=AUTHORIZED."""
        tools = registry.get_visible_tools(step_up_state)
        names = [t.name for t in tools]
        assert "stub_execution" in names

    def test_openai_schemas_match_visible_tools(self, registry, step_up_state):
        schemas = registry.get_openai_schemas(step_up_state)
        names = [s["function"]["name"] for s in schemas]
        tools = registry.get_visible_tools(step_up_state)
        tool_names = [t.name for t in tools]
        assert set(names) == set(tool_names)


# ── Channel override tests ────────────────────────────────────────────────────

class TestChannelOverrides:
    def test_channel_restricts_tools(self, registry, step_up_state):
        registry.set_channel_tools("chat", {"stub_read", "stub_proposal"})
        tools = registry.get_visible_tools(step_up_state, channel="chat")
        names = [t.name for t in tools]
        assert "stub_read" in names
        assert "stub_proposal" in names
        # Execution tool excluded from chat channel
        assert "stub_execution" not in names

    def test_sms_allows_all(self, registry, step_up_state):
        registry.set_channel_tools("sms", {"stub_read", "stub_proposal", "stub_execution"})
        tools = registry.get_visible_tools(step_up_state, channel="sms")
        names = [t.name for t in tools]
        assert "stub_execution" in names


# ── Invocation tests ──────────────────────────────────────────────────────────

class TestToolInvocation:
    async def test_invoke_read_tool(self, registry, base_state):
        envelope = ToolEnvelope.create(
            conversation_id="c", turn_id="t", customer_id="cust",
            auth_level="verified", account_id="ACC-001", intent_type="read",
        )
        result = await registry.invoke("stub_read", envelope, base_state)
        assert result.status == "confirmed"
        assert result.data["read"] is True

    async def test_invoke_unknown_tool_rejected(self, registry, base_state):
        envelope = ToolEnvelope.create(
            conversation_id="c", turn_id="t", customer_id="cust",
            auth_level="verified", intent_type="unknown",
        )
        result = await registry.invoke("nonexistent_tool", envelope, base_state)
        assert result.status == "invalid_request"
        assert "Unknown tool" in result.error

    async def test_invoke_execution_without_auth_rejected(self, registry, base_state):
        """Execution tool without authorization_ref should be rejected."""
        state = dict(base_state)
        state["action_status"] = "AUTHORIZED"
        envelope = ToolEnvelope.create(
            conversation_id="c", turn_id="t", customer_id="cust",
            auth_level="step_up", account_id="ACC-001",
            intent_type="execute",
        )
        # No authorization_ref set
        result = await registry.invoke("stub_execution", envelope, state)
        assert result.status == "invalid_request"
        assert "Authorization artifact required" in result.error

    async def test_invoke_execution_without_step_up_rejected(self, registry, base_state):
        """Execution tool without step-up auth should be rejected."""
        state = dict(base_state)
        state["action_status"] = "AUTHORIZED"
        envelope = ToolEnvelope.create(
            conversation_id="c", turn_id="t", customer_id="cust",
            auth_level="verified", account_id="ACC-001",
            intent_type="execute",
            authorization_ref="auth_001",
        )
        result = await registry.invoke("stub_execution", envelope, state)
        assert result.status == "invalid_request"
        assert "Step-up authentication required" in result.error

    async def test_invoke_execution_with_auth_succeeds(self, registry, step_up_state):
        """Execution tool with step-up auth + authorization_ref should succeed."""
        envelope = ToolEnvelope.create(
            conversation_id="c", turn_id="t", customer_id="cust",
            auth_level="step_up", account_id="ACC-001",
            intent_type="execute",
            authorization_ref="auth_001",
        )
        result = await registry.invoke("stub_execution", envelope, step_up_state)
        assert result.status == "confirmed"
        assert result.data["executed"] is True

    async def test_invoke_with_preconditions_not_met(self, registry, base_state):
        """Execution tool with preconditions not met should be rejected."""
        state = dict(base_state)
        state["action_status"] = "PROPOSED"  # Not AUTHORIZED
        envelope = ToolEnvelope.create(
            conversation_id="c", turn_id="t", customer_id="cust",
            auth_level="step_up", account_id="ACC-001",
            intent_type="execute",
            authorization_ref="auth_001",
        )
        result = await registry.invoke("stub_execution", envelope, state)
        assert result.status == "invalid_request"
        assert "preconditions not met" in result.error
