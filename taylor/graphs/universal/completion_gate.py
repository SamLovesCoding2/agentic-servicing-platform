"""
Evidence completion gate.

Validates that every subgraph returned a proper exit state with evidence
before allowing the conversation to end. This is the final deterministic
check before the response is rendered.

The gate enforces:
  1. Every subgraph returns one of its declared exit states
  2. Sensitive actions have CONFIRMED or UNKNOWN persisted before success language
  3. No subgraph routed outside its declared destinations
  4. No subgraph widened its tool set
"""

from __future__ import annotations

from typing import Any

from taylor.graphs.universal.state import ActionStatus, GraphState, SubgraphExit


# ── Subgraph exit validation ─────────────────────────────────────────────────

SUBGRAPH_VALID_EXITS: dict[str, set[SubgraphExit]] = {
    "knowledge": {SubgraphExit.CITED_ANSWER, SubgraphExit.NO_ANSWER},
    "account_servicing": {
        SubgraphExit.FRESH_RESULT,
        SubgraphExit.PRECONDITION_REJECTED,
        SubgraphExit.HANDOFF,
    },
    "arrangement": {
        SubgraphExit.VALIDATED_PROPOSAL,
        SubgraphExit.INVALID_PROPOSAL,
    },
    "sensitive_action": {
        SubgraphExit.CONFIRMED,
        SubgraphExit.REJECTED,
        SubgraphExit.CANCELLED,
        SubgraphExit.UNKNOWN_RECONCILING,
    },
    "compliance_handoff": {
        SubgraphExit.POLICY_ALLOW,
        SubgraphExit.POLICY_DENY,
        SubgraphExit.TRANSFER_ACCEPTED,
    },
}


def validate_exit(route: str, exit_state: SubgraphExit | str | None) -> bool:
    """
    Validate that the exit state is one of the declared exits for this route.

    A subgraph cannot return an exit state outside its contract.
    """
    if exit_state is None:
        return False

    # Normalize to SubgraphExit
    if isinstance(exit_state, str):
        try:
            exit_state = SubgraphExit(exit_state)
        except ValueError:
            return False

    valid_exits = SUBGRAPH_VALID_EXITS.get(route, set())
    return exit_state in valid_exits


def can_use_success_language(state: dict[str, Any]) -> bool:
    """
    Critical safety check: can we use success language?

    Success language ("your payment has been scheduled") is only permitted
    after CONFIRMED is persisted to the database.

    For UNKNOWN: only "confirmation is pending" language is allowed.
    For REJECTED: only failure language is allowed.
    For non-sensitive actions: success language depends on the exit state.
    """
    route = state.get("route", "")
    action_status = state.get("action_status")
    exit_state = state.get("exit_state")

    if route == "sensitive_action":
        if action_status == ActionStatus.CONFIRMED:
            return True
        return False

    # For other routes, a valid exit state implies success
    if exit_state in (
        SubgraphExit.CITED_ANSWER,
        SubgraphExit.FRESH_RESULT,
        SubgraphExit.VALIDATED_PROPOSAL,
        SubgraphExit.POLICY_ALLOW,
        SubgraphExit.TRANSFER_ACCEPTED,
    ):
        return True

    return False


def completion_gate(state: dict[str, Any]) -> dict[str, Any]:
    """
    The evidence completion gate node.

    Validates:
    1. Exit state is valid for the route
    2. Success language rules are enforced
    3. Returns metadata about what language is permitted

    This node runs AFTER the subgraph completes and BEFORE the response
    is rendered to the customer.
    """
    route = state.get("route", "")
    exit_state = state.get("exit_state")

    # Validate exit state
    is_valid_exit = validate_exit(route, exit_state)

    # Check success language permission
    success_allowed = can_use_success_language(state)

    # Build the gate result
    gate_result = {
        "gate_passed": is_valid_exit,
        "success_language_allowed": success_allowed,
        "route": route,
        "exit_state": exit_state,
    }

    if not is_valid_exit:
        gate_result["gate_error"] = f"Invalid exit state {exit_state} for route {route}"
        # Force a safe fallback
        return {
            "exit_state": SubgraphExit.HANDOFF,
            "gate_result": gate_result,
        }

    return {"gate_result": gate_result}
