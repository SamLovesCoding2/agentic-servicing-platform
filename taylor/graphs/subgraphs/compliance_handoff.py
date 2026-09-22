"""
Compliance and handoff subgraph.

Handles policy evaluation, compliance-sensitive phrases (death, bankruptcy,
attorney, dispute), and human transfer. May preempt every other subgraph.

Contract:
  - Allowed inputs: current action, channel, policy context, customer language
  - Writable state: policy decision, transfer request
  - Tool authority: policy evaluation, human-transfer tools
  - Required exits: policy_allow, policy_deny, transfer_accepted
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, StateGraph

from taylor.graphs.universal.state import GraphState, SubgraphExit

# Compliance-sensitive phrases that require special handling
COMPLIANCE_PHRASES: list[str] = [
    "death",
    "deceased",
    "bankruptcy",
    "bankrupt",
    "attorney",
    "lawyer",
    "legal counsel",
    "dispute",
    "not my debt",
    "identity theft",
    "cease and desist",
]


def detect_compliance_phrase(text: str) -> str | None:
    """Check if the utterance contains a compliance-sensitive phrase."""
    text_lower = text.lower()
    for phrase in COMPLIANCE_PHRASES:
        if phrase in text_lower:
            return phrase
    return None


def evaluate_policy_node(state: dict[str, Any]) -> dict[str, Any]:
    """
    Evaluate policy for the current action.
    In M1, this is a simple compliance phrase check.
    In M2, this will call the full compliance engine.
    """
    utterance = state.get("utterance", "")
    detected = detect_compliance_phrase(utterance)

    if detected:
        return {
            "route": "compliance_handoff",
            "exit_state": SubgraphExit.POLICY_DENY,
            "action_result": {
                "compliance_phrase": detected,
                "action_required": "human_handoff",
                "message": f"Compliance-sensitive phrase detected: '{detected}'. Transferring to human agent.",
            },
        }

    return {
        "route": "compliance_handoff",
        "exit_state": SubgraphExit.POLICY_ALLOW,
    }


def transfer_node(state: dict[str, Any]) -> dict[str, Any]:
    """Initiate human transfer."""
    return {
        "exit_state": SubgraphExit.TRANSFER_ACCEPTED,
        "action_result": {
            "transfer_initiated": True,
            "reason": "compliance_phrase_detected",
        },
    }


def route_after_policy(state: dict[str, Any]) -> str:
    """Conditional edge: allow, deny (with transfer), or just deny."""
    exit_state = state.get("exit_state")
    if exit_state == SubgraphExit.POLICY_DENY:
        return "transfer"
    return "end"


def build_compliance_handoff_subgraph() -> StateGraph:
    """
    Build the compliance/handoff subgraph.

    Structure:
        evaluate_policy → [allow?] → END
                        → transfer → END
    """
    graph = StateGraph(GraphState)

    graph.add_node("evaluate_policy", evaluate_policy_node)
    graph.add_node("transfer", transfer_node)

    graph.set_entry_point("evaluate_policy")
    graph.add_conditional_edges(
        "evaluate_policy",
        route_after_policy,
        {
            "transfer": "transfer",
            "end": END,
        },
    )
    graph.add_edge("transfer", END)

    return graph


COMPLIANCE_HANDOFF_CONTRACT = {
    "name": "compliance_handoff",
    "allowed_inputs": ["utterance", "channel", "action_status", "action_intent"],
    "writable_state": ["exit_state", "route", "action_result"],
    "tool_authority": ["execution"],  # transfer_to_agent is execution
    "required_exits": [SubgraphExit.POLICY_ALLOW, SubgraphExit.POLICY_DENY, SubgraphExit.TRANSFER_ACCEPTED],
}
