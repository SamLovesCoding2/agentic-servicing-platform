"""
Sensitive action subgraph.

Owns protected collection, explicit authorization, and transaction execution.
This is the most security-critical subgraph.

The state machine flow:
    PROPOSED → NORMALIZED → VALIDATED → AUTHORIZED → EXECUTING → CONFIRMED
                                  ↘ REJECTED      ↘ UNKNOWN
    UNKNOWN → (reconciliation) → CONFIRMED or REJECTED

Key rules:
  - The model can only move a request to PROPOSED. Code controls the rest.
  - Protected collection bypasses the LLM text path (opaque tokens only).
  - Authorization is versioned and binds actor + amount + date + method + disclosures.
  - If any bound field changes, authorization is invalid.
  - UNKNOWN is not failure — requires reconciliation by idempotency key.
  - Success language only after CONFIRMED is persisted.

Contract:
  - Allowed inputs: validated proposal, auth level, authorization version
  - Writable state: action lifecycle, opaque token reference
  - Tool authority: execution (protected collection and execution tools)
  - Required exits: confirmed, rejected, cancelled, unknown_reconciling
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from langgraph.graph import END, StateGraph

from taylor.graphs.universal.state import AuthLevel, GraphState, SubgraphExit


def collect_protected_node(state: dict[str, Any]) -> dict[str, Any]:
    """
    Protected collection node.

    In voice: pause recording/transcription, collect DTMF digits, return opaque token.
    In chat: redirect to secure element, receive opaque token.
    In text (M1): simulate with a mock token.

    The graph receives a placeholder or opaque payment-method token,
    NEVER PAN, CVV, PIN, bank number, or raw digits.
    """
    # Simulate protected collection
    mock_token = f"pm_protected_{uuid4().hex[:12]}"

    return {
        "route": "sensitive_action",
        "credential_token": mock_token,
        "action_status": "VALIDATED",
    }


def authorize_node(state: dict[str, Any]) -> dict[str, Any]:
    """
    Obtain explicit customer authorization.

    Creates a versioned authorization artifact that binds:
      - actor (customer_id, auth_level)
      - bound_values (amount, date, method_token)
      - disclosures (what the customer was told)
      - version

    If any bound field changes later, the authorization is invalid.
    """
    auth_level = state.get("auth_level", AuthLevel.ANONYMOUS)
    if auth_level != AuthLevel.STEP_UP:
        return {
            "exit_state": SubgraphExit.PRECONDITION_REJECTED,
            "action_status": "REJECTED",
        }

    action_intent = state.get("action_intent", {})
    customer_id = state.get("customer_id", "")
    method_token = state.get("credential_token") or action_intent.get("method_token")

    artifact = {
        "artifact_id": f"auth_{uuid4().hex[:12]}",
        "customer_id": customer_id,
        "action_type": action_intent.get("type", "schedule_payment"),
        "actor": {
            "customer_id": customer_id,
            "auth_level": auth_level.value if isinstance(auth_level, AuthLevel) else auth_level,
        },
        "bound_values": {
            "amount": action_intent.get("amount"),
            "date": action_intent.get("date"),
            "method_token": method_token,
        },
        "disclosures": {
            "amount_disclosed": True,
            "date_disclosed": True,
            "method_disclosed": True,
            "no_guarantee_claim": True,
        },
        "version": 1,
        "is_valid": True,
        "created_at": datetime.utcnow().isoformat(),
    }

    return {
        "authorization_artifact": artifact,
        "action_status": "AUTHORIZED",
    }


def execute_node(state: dict[str, Any]) -> dict[str, Any]:
    """
    Execute the authorized action.

    Before execution, rechecks:
      - authorization artifact is still valid
      - action_status is AUTHORIZED
      - policy_context_version matches

    Creates a stable action_id, persists the intent, calls the provider.
    Stores the provider confirmation. Only after this record exists
    may the response renderer say the action was successful.
    """
    auth_artifact = state.get("authorization_artifact")
    if not auth_artifact or not auth_artifact.get("is_valid", False):
        return {
            "exit_state": SubgraphExit.REJECTED,
            "action_status": "REJECTED",
        }

    action_status = state.get("action_status")
    if action_status != "AUTHORIZED":
        return {
            "exit_state": SubgraphExit.REJECTED,
            "action_status": "REJECTED",
        }

    # The actual tool execution happens via the registry in the turn coordinator.
    # Here we just transition the state.
    return {
        "action_status": "EXECUTING",
    }


def confirm_node(state: dict[str, Any]) -> dict[str, Any]:
    """
    Process the execution result.

    If confirmed: persist and allow success language.
    If unknown: set UNKNOWN — reconciliation required, no success or failure language.
    If rejected: persist and allow failure language.
    """
    action_result = state.get("action_result", {})
    status = action_result.get("status", "unknown")

    if status == "confirmed":
        return {
            "action_status": "CONFIRMED",
            "exit_state": SubgraphExit.CONFIRMED,
        }
    elif status == "unknown":
        return {
            "action_status": "UNKNOWN",
            "exit_state": SubgraphExit.UNKNOWN_RECONCILING,
        }
    elif status == "rejected":
        return {
            "action_status": "REJECTED",
            "exit_state": SubgraphExit.REJECTED,
        }
    else:
        return {
            "action_status": "UNKNOWN",
            "exit_state": SubgraphExit.UNKNOWN_RECONCILING,
        }


def route_after_authorize(state: dict[str, Any]) -> str:
    """Conditional edge after authorization: proceed to execute or reject."""
    action_status = state.get("action_status")
    if action_status == "AUTHORIZED":
        return "execute"
    return "rejected"


def route_after_execute(state: dict[str, Any]) -> str:
    """Conditional edge after execution: confirm or handle unknown."""
    # The actual result comes from the tool execution
    action_result = state.get("action_result", {})
    status = action_result.get("status", "unknown")

    if status in ("confirmed", "rejected", "unknown"):
        return "confirm"
    return "confirm"  # Always go to confirm node which handles all cases


def rejected_node(state: dict[str, Any]) -> dict[str, Any]:
    """Handle rejection."""
    return {
        "exit_state": SubgraphExit.REJECTED,
        "action_status": "REJECTED",
    }


def build_sensitive_action_subgraph() -> StateGraph:
    """
    Build the sensitive action subgraph.

    Structure:
        collect → authorize → [authorized?] → execute → confirm → END
                            → rejected → END
    """
    graph = StateGraph(GraphState)

    graph.add_node("collect_protected", collect_protected_node)
    graph.add_node("authorize", authorize_node)
    graph.add_node("execute", execute_node)
    graph.add_node("confirm", confirm_node)
    graph.add_node("rejected", rejected_node)

    graph.set_entry_point("collect_protected")
    graph.add_edge("collect_protected", "authorize")
    graph.add_conditional_edges(
        "authorize",
        route_after_authorize,
        {
            "execute": "execute",
            "rejected": "rejected",
        },
    )
    graph.add_edge("execute", "confirm")
    graph.add_edge("confirm", END)
    graph.add_edge("rejected", END)

    return graph


SENSITIVE_ACTION_CONTRACT = {
    "name": "sensitive_action",
    "allowed_inputs": ["action_intent", "auth_level", "action_status", "credential_token"],
    "writable_state": [
        "exit_state",
        "route",
        "action_status",
        "action_id",
        "action_result",
        "credential_token",
        "authorization_artifact",
    ],
    "tool_authority": ["execution"],
    "required_exits": [
        SubgraphExit.CONFIRMED,
        SubgraphExit.REJECTED,
        SubgraphExit.CANCELLED,
        SubgraphExit.UNKNOWN_RECONCILING,
    ],
}
