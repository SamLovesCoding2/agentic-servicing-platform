"""
Intent router.

Deterministic entry with classifier assistance.
1. Read authenticated session state and current utterance
2. Run a classifier (rule-based in M1, LLM-assisted in production) to propose a route
3. Validate the proposed route against allowed transitions for this channel + auth level
4. If invalid or ambiguous, fall back to knowledge subgraph (safe default)

The router does NOT ask an unconstrained model to choose from every node.
It offers a bounded choice validated by code.
"""

from __future__ import annotations

import re
from typing import Any

from taylor.graphs.universal.state import AuthLevel, Channel

# ── Route definitions ─────────────────────────────────────────────────────────

class Route(str):
    KNOWLEDGE = "knowledge"
    ACCOUNT_SERVICING = "account_servicing"
    ARRANGEMENT = "arrangement"
    SENSITIVE_ACTION = "sensitive_action"
    COMPLIANCE_HANDOFF = "compliance_handoff"


# Channel-specific allowed routes
CHANNEL_ROUTES: dict[str, set[str]] = {
    Channel.SMS.value: {
        Route.KNOWLEDGE,
        Route.ACCOUNT_SERVICING,
        Route.ARRANGEMENT,
        Route.SENSITIVE_ACTION,
        Route.COMPLIANCE_HANDOFF,
    },
    Channel.CHAT.value: {
        Route.KNOWLEDGE,
        Route.ACCOUNT_SERVICING,
        Route.ARRANGEMENT,
        Route.COMPLIANCE_HANDOFF,
        # NOTE: SENSITIVE_ACTION intentionally excluded from chat
        # Chat cannot take payments — this is architectural, not a prompt issue
    },
    Channel.VOICE.value: {
        Route.KNOWLEDGE,
        Route.ACCOUNT_SERVICING,
        Route.ARRANGEMENT,
        Route.SENSITIVE_ACTION,
        Route.COMPLIANCE_HANDOFF,
    },
}

# Auth-level requirements per route
AUTH_REQUIREMENTS: dict[str, AuthLevel] = {
    Route.KNOWLEDGE: AuthLevel.ANONYMOUS,       # FAQ is public
    Route.ACCOUNT_SERVICING: AuthLevel.VERIFIED,  # Must be authenticated
    Route.ARRANGEMENT: AuthLevel.VERIFIED,        # Must see account to propose
    Route.SENSITIVE_ACTION: AuthLevel.STEP_UP,    # Requires step-up auth
    Route.COMPLIANCE_HANDOFF: AuthLevel.ANONYMOUS, # Anyone can trigger handoff
}


# ── Rule-based classifier (M1) ───────────────────────────────────────────────

# Intent patterns: (regex, route)
INTENT_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Compliance phrases (highest priority — preempt everything)
    (re.compile(r"\b(death|deceased|bankruptcy|bankrupt|attorney|lawyer|dispute|cease)\b", re.I), Route.COMPLIANCE_HANDOFF),
    # Transfer requests
    (re.compile(r"\b(human|agent|representative|talk to someone|manager)\b", re.I), Route.COMPLIANCE_HANDOFF),
    # Arrangement: settlements, payment plans, payoff quotes (check before sensitive)
    (re.compile(r"\b(settle|settlement|payment plan|installment|payoff|pay off)\b", re.I), Route.ARRANGEMENT),
    # Account servicing: specific action words
    (re.compile(r"\b(update|change|new phone|new address|balance|due date|how much do i owe|how much is my)\b", re.I), Route.ACCOUNT_SERVICING),
    # Knowledge: questions starting with question words (check before sensitive action
    # so "What happens if I miss a payment?" → knowledge, not sensitive_action)
    (re.compile(r"^(how|what|why|when|where|can i|do you|is|are)\b", re.I), Route.KNOWLEDGE),
    # Sensitive action: paying (standalone "pay" or "payment" as an action verb)
    (re.compile(r"\b(pay|payment|charge|card|bank account)\b", re.I), Route.SENSITIVE_ACTION),
    # Knowledge: other question patterns (fallback)
    (re.compile(r"\b(how|what|why|when|where|can i|do you|policy|faq|question)\b", re.I), Route.KNOWLEDGE),
]


def classify_intent(utterance: str) -> str:
    """
    Rule-based intent classification.

    In production, this would be an LLM call with structured output
    validated against allowed routes. In M1, we use regex patterns.

    The classifier proposes a route; the router validates it.
    """
    if not utterance or not utterance.strip():
        return Route.KNOWLEDGE  # Safe default for empty input

    for pattern, route in INTENT_PATTERNS:
        if pattern.search(utterance):
            return route

    return Route.KNOWLEDGE  # Safe default


# ── Router ────────────────────────────────────────────────────────────────────

def validate_route(
    proposed_route: str,
    channel: str,
    auth_level: AuthLevel | str,
) -> bool:
    """
    Validate that the proposed route is allowed for this channel + auth level.

    This is the deterministic validation layer. The classifier can propose
    anything; this function enforces what's actually permitted.
    """
    # Normalize auth_level
    if isinstance(auth_level, AuthLevel):
        auth = auth_level
    else:
        auth = AuthLevel(auth_level)

    # Check channel allows this route
    allowed_routes = CHANNEL_ROUTES.get(channel, set())
    if proposed_route not in allowed_routes:
        return False

    # Check auth level is sufficient
    required_auth = AUTH_REQUIREMENTS.get(proposed_route, AuthLevel.VERIFIED)

    # Auth hierarchy: anonymous < verified < step_up
    auth_levels = [AuthLevel.ANONYMOUS, AuthLevel.VERIFIED, AuthLevel.STEP_UP]
    return auth_levels.index(auth) >= auth_levels.index(required_auth)


def route(state: dict[str, Any]) -> dict[str, Any]:
    """
    Main routing function.

    1. Check for compliance phrases first (preempt everything)
    2. Classify intent
    3. Validate route against channel + auth constraints
    4. Fall back to knowledge if invalid
    """
    utterance = state.get("utterance", "")
    channel = state.get("channel", Channel.SMS.value)
    auth_level = state.get("auth_level", AuthLevel.ANONYMOUS)

    # Preempt: check for compliance phrases first
    from taylor.graphs.subgraphs.compliance_handoff import detect_compliance_phrase
    compliance_phrase = detect_compliance_phrase(utterance)
    if compliance_phrase:
        return {
            "route": Route.COMPLIANCE_HANDOFF,
            "detected_intent": "compliance_phrase",
        }

    # Classify
    proposed = classify_intent(utterance)

    # Validate
    if validate_route(proposed, channel, auth_level):
        return {
            "route": proposed,
            "detected_intent": proposed,
        }

    # Fall back to knowledge (safe default)
    # If the route was rejected, it's likely because auth is insufficient.
    # In production, we'd trigger step-up auth here.
    return {
        "route": Route.KNOWLEDGE,
        "detected_intent": "auth_insufficient_fallback",
    }
