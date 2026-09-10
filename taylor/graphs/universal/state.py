"""
Graph state schema and reducers.

Four-category state model:
  - TurnState: ephemeral, per-turn reasoning context
  - SessionState: conversation runtime, versioned + checkpointed
  - BusinessState: system of record, durable workflow
  - ProtectedState: isolated vault, never in graph messages or prompts

Reducer semantics:
  - Messages: append-only (never lose conversational context)
  - collected_slots: merge (union of keys)
  - pending_confirmation: compare-and-set (prevent race between correction and execution)
  - selected_payment_method: replace-only (new selection invalidates old)
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Annotated, Any, TypedDict

from langgraph.graph.message import add_messages


# ── Enums ───────────────────────────────────────────────────────────────────

class AuthLevel(str, Enum):
    ANONYMOUS = "anonymous"
    VERIFIED = "verified"
    STEP_UP = "step_up"


class Channel(str, Enum):
    SMS = "sms"
    CHAT = "chat"
    VOICE = "voice"


class ActionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    NORMALIZED = "NORMALIZED"
    VALIDATED = "VALIDATED"
    AUTHORIZED = "AUTHORIZED"
    EXECUTING = "EXECUTING"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


class SubgraphExit(str, Enum):
    """Required exit states for subgraph contracts."""
    CITED_ANSWER = "cited_answer"
    NO_ANSWER = "no_answer"
    FRESH_RESULT = "fresh_result"
    PRECONDITION_REJECTED = "precondition_rejected"
    HANDOFF = "handoff"
    VALIDATED_PROPOSAL = "validated_proposal"
    INVALID_PROPOSAL = "invalid_proposal"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    UNKNOWN_RECONCILING = "unknown_reconciling"
    POLICY_ALLOW = "policy_allow"
    POLICY_DENY = "policy_deny"
    TRANSFER_ACCEPTED = "transfer_accepted"


# ── Reducers ────────────────────────────────────────────────────────────────

def merge_slots(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    """Merge reducer: union of keys, right wins on conflict."""
    if left is None:
        left = {}
    if right is None:
        right = {}
    return {**left, **right}


def compare_and_set(left: Any, right: Any) -> Any:
    """
    Compare-and-set reducer for pending_confirmation.
    Prevents a correction from racing with execution.

    Rules:
    - If right is None, clear the pending confirmation (execution completed or cancelled).
    - If left is None and right is not None, set to right (new confirmation).
    - If both are not None, check the 'version' field. Right must have a higher
      version than left. If not, left wins (stale update rejected).
    - If no version field, right wins (last write).
    """
    if right is None:
        return None
    if left is None:
        return right
    if isinstance(left, dict) and isinstance(right, dict):
        left_version = left.get("version", 0)
        right_version = right.get("version", 0)
        # When both have default version (0), right wins (last write)
        if left_version == 0 and right_version == 0:
            return right
        if right_version > left_version:
            return right
        return left  # Stale update rejected
    return right


def replace(left: Any, right: Any) -> Any:
    """Replace reducer: right always wins, including None."""
    return right


# ── State Categories ─────────────────────────────────────────────────────────

class TurnState(TypedDict, total=False):
    """Ephemeral, per-turn reasoning context."""
    utterance: str
    detected_intent: str | None
    tool_request: dict[str, Any] | None
    turn_id: str
    turn_started_at: float  # epoch seconds, for loop budget enforcement


class SessionState(TypedDict, total=False):
    """Conversation runtime, versioned + checkpointed."""
    conversation_id: str
    customer_id: str  # server-derived, never model-supplied
    auth_level: AuthLevel
    locale: str
    channel: Channel
    collected_slots: Annotated[dict[str, Any], merge_slots]
    pending_confirmation: Annotated[dict[str, Any] | None, compare_and_set]
    selected_payment_method: Annotated[str | None, replace]


class BusinessState(TypedDict, total=False):
    """System of record or durable workflow."""
    account_id: str
    account_balance: Decimal
    due_date: date | None
    payment_status: str | None
    contact_permissions: dict[str, Any]
    negotiation_rules: dict[str, Any]


class ProtectedState(TypedDict, total=False):
    """
    Isolated vault. NEVER in graph messages, prompts, traces, or analytics.
    These fields hold opaque tokens and authorization artifacts only.
    """
    credential_token: str | None  # opaque payment method token
    authorization_artifact: dict[str, Any] | None  # versioned consent


# ── Combined Graph State ─────────────────────────────────────────────────────

class GraphState(TypedDict, total=False):
    """
    The complete graph state. Combines all four categories.
    Subgraphs may use private state internally and publish only
    a narrow result to the parent.
    """
    # Messages (append-only via LangGraph's add_messages reducer)
    messages: Annotated[list, add_messages]

    # Turn state
    utterance: str
    detected_intent: str | None
    tool_request: dict[str, Any] | None
    turn_id: str
    turn_started_at: float

    # Session state
    conversation_id: str
    customer_id: str
    auth_level: AuthLevel
    locale: str
    channel: Channel
    collected_slots: Annotated[dict[str, Any], merge_slots]
    pending_confirmation: Annotated[dict[str, Any] | None, compare_and_set]
    selected_payment_method: Annotated[str | None, replace]

    # Business state
    account_id: str
    account_balance: Decimal
    due_date: date | None
    payment_status: str | None
    contact_permissions: dict[str, Any]
    negotiation_rules: dict[str, Any]

    # Protected state (never serialized to model)
    credential_token: str | None
    authorization_artifact: dict[str, Any] | None

    # Action lifecycle (sensitive action state machine)
    action_status: ActionStatus
    action_id: str | None
    action_intent: dict[str, Any] | None
    action_result: dict[str, Any] | None

    # Graph control
    route: str | None  # which subgraph was selected
    exit_state: SubgraphExit | None  # subgraph exit contract
    model_turn_count: int
    tool_attempt_counts: dict[str, int]
    gate_result: dict[str, Any] | None


# ── Subgraph contract types ─────────────────────────────────────────────────

class SubgraphContract(TypedDict, total=False):
    """Contract each subgraph publishes. Enforced by the parent graph."""
    name: str
    allowed_inputs: list[str]
    writable_state: list[str]
    tool_authority: list[str]  # tool class: read, proposal, execution
    required_exits: list[SubgraphExit]
