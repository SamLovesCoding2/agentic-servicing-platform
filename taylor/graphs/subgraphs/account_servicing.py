"""
Account servicing subgraph.

Scoped account reads and allowlisted reversible updates.
Can read balance, due date, status, and update phone/address.

Contract:
  - Allowed inputs: authenticated account reference, requested field
  - Writable state: fresh result, servicing proposal
  - Tool authority: read (account data), execution (reversible updates only)
  - Required exits: fresh_result, precondition_rejected, handoff
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, StateGraph

from taylor.graphs.universal.state import AuthLevel, GraphState, SubgraphExit


def read_account_node(state: dict[str, Any]) -> dict[str, Any]:
    """Read account data (balance, due date, status)."""
    auth_level = state.get("auth_level", AuthLevel.ANONYMOUS)
    if auth_level == AuthLevel.ANONYMOUS:
        return {"exit_state": SubgraphExit.PRECONDITION_REJECTED}

    return {
        "route": "account_servicing",
        "exit_state": SubgraphExit.FRESH_RESULT,
    }


def update_servicing_node(state: dict[str, Any]) -> dict[str, Any]:
    """Update a reversible field (phone, address). Requires step-up auth."""
    auth_level = state.get("auth_level", AuthLevel.ANONYMOUS)
    if auth_level != AuthLevel.STEP_UP:
        return {"exit_state": SubgraphExit.PRECONDITION_REJECTED}

    return {
        "route": "account_servicing",
        "exit_state": SubgraphExit.FRESH_RESULT,
    }


def route_servicing(state: dict[str, Any]) -> str:
    """Route based on intent: read vs. update."""
    utterance = state.get("utterance", "").lower()
    if any(w in utterance for w in ["update", "change", "new phone", "new address"]):
        return "update"
    return "read"


def build_account_servicing_subgraph() -> StateGraph:
    """
    Build the account servicing subgraph.

    Structure:
        entry → [read or update?] → read_account → END
                                → update_servicing → END
    """
    graph = StateGraph(GraphState)

    graph.add_node("read_account", read_account_node)
    graph.add_node("update_servicing", update_servicing_node)

    graph.set_entry_point("read_account")  # Default entry; router handles routing

    graph.add_edge("read_account", END)
    graph.add_edge("update_servicing", END)

    return graph


ACCOUNT_SERVICING_CONTRACT = {
    "name": "account_servicing",
    "allowed_inputs": ["utterance", "auth_level", "account_id"],
    "writable_state": ["exit_state", "route", "collected_slots"],
    "tool_authority": ["read", "execution"],  # execution only for reversible updates
    "required_exits": [SubgraphExit.FRESH_RESULT, SubgraphExit.PRECONDITION_REJECTED, SubgraphExit.HANDOFF],
}
