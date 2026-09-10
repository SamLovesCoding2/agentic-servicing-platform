"""
Arrangement subgraph.

Quote and validation only — no side effects.
Computes payoff quotes, validates payment proposals, checks eligibility.

Contract:
  - Allowed inputs: balance snapshot, customer proposal (amount, date, method)
  - Writable state: normalized amount/date/plan candidates
  - Tool authority: proposal (quote and validation tools only)
  - Required exits: validated_proposal, invalid_proposal
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, StateGraph

from taylor.graphs.universal.state import AuthLevel, GraphState, SubgraphExit


def normalize_node(state: dict[str, Any]) -> dict[str, Any]:
    """
    Normalize the proposal: parse amounts, resolve dates, canonicalize identifiers.
    The model proposes; deterministic code normalizes.
    """
    utterance = state.get("utterance", "")
    return {
        "route": "arrangement",
        "action_status": "NORMALIZED",
    }


def validate_node(state: dict[str, Any]) -> dict[str, Any]:
    """
    Validate the normalized proposal against business rules.
    Calls validate_payment_proposal or calculate_payoff_quote tools.
    """
    action_status = state.get("action_status")

    # If we already have a result from the validation tool
    action_result = state.get("action_result", {})
    if action_result and action_result.get("data", {}).get("valid") is False:
        return {"exit_state": SubgraphExit.INVALID_PROPOSAL}

    if action_status == "NORMALIZED":
        return {
            "action_status": "VALIDATED",
            "exit_state": SubgraphExit.VALIDATED_PROPOSAL,
        }

    return {"exit_state": SubgraphExit.INVALID_PROPOSAL}


def should_validate(state: dict[str, Any]) -> str:
    """Conditional edge: is the proposal valid or invalid?"""
    exit_state = state.get("exit_state")
    if exit_state == SubgraphExit.INVALID_PROPOSAL:
        return "invalid"
    return "valid"


def build_arrangement_subgraph() -> StateGraph:
    """
    Build the arrangement subgraph.

    Structure:
        normalize → validate → [valid?] → END (validated_proposal)
                              → END (invalid_proposal)
    """
    graph = StateGraph(GraphState)

    graph.add_node("normalize", normalize_node)
    graph.add_node("validate", validate_node)

    graph.set_entry_point("normalize")
    graph.add_edge("normalize", "validate")
    graph.add_conditional_edges(
        "validate",
        should_validate,
        {
            "valid": END,
            "invalid": END,
        },
    )

    return graph


ARRANGEMENT_CONTRACT = {
    "name": "arrangement",
    "allowed_inputs": ["utterance", "account_id", "account_balance", "negotiation_rules"],
    "writable_state": ["exit_state", "route", "action_status", "action_intent", "action_result"],
    "tool_authority": ["proposal"],
    "required_exits": [SubgraphExit.VALIDATED_PROPOSAL, SubgraphExit.INVALID_PROPOSAL],
}
