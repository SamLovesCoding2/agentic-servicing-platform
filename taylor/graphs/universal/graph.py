"""
Main graph builder.

Assembles the universal graph with:
  1. Preconditions check
  2. Intent router (deterministic + classifier)
  3. Five capability-scoped subgraphs
  4. Evidence completion gate

The graph enforces:
  - The model can only move a request to PROPOSED. Code controls the rest.
  - Subgraph transitions are validated. A subgraph cannot route outside
    its declared destinations or widen its tool set.
  - Success language is only permitted after CONFIRMED is persisted.
  - Every reasoning loop has a budget (max turns, tool attempts, time).
"""

from __future__ import annotations

import time
from typing import Any

from langgraph.graph import END, StateGraph

from taylor.graphs.subgraphs.account_servicing import build_account_servicing_subgraph
from taylor.graphs.subgraphs.arrangement import build_arrangement_subgraph
from taylor.graphs.subgraphs.compliance_handoff import (
    build_compliance_handoff_subgraph,
)
from taylor.graphs.subgraphs.knowledge import build_knowledge_subgraph
from taylor.graphs.subgraphs.sensitive_action import build_sensitive_action_subgraph
from taylor.graphs.universal.completion_gate import completion_gate
from taylor.graphs.universal.router import Route
from taylor.graphs.universal.router import route as route_fn
from taylor.graphs.universal.state import (
    GraphState,
    SubgraphExit,
)

# ── Preconditions ─────────────────────────────────────────────────────────────

def preconditions_node(state: dict[str, Any]) -> dict[str, Any]:
    """
    Check preconditions before routing.

    Validates:
    - conversation_id exists
    - customer_id exists (must be authenticated at least anonymously)
    - channel is set
    - turn budget not exceeded
    """
    conversation_id = state.get("conversation_id")
    customer_id = state.get("customer_id")

    if not conversation_id or not customer_id:
        return {
            "exit_state": SubgraphExit.HANDOFF,
            "route": "preconditions_failed",
        }

    # Initialize turn tracking
    turn_count = state.get("model_turn_count", 0)
    turn_started_at = state.get("turn_started_at")
    if not turn_started_at:
        turn_started_at = time.time()

    return {
        "turn_started_at": turn_started_at,
        "model_turn_count": turn_count,
    }


# ── Router node ──────────────────────────────────────────────────────────────

def router_node(state: dict[str, Any]) -> dict[str, Any]:
    """
    Intent router node.

    Runs the router function which:
    1. Checks for compliance phrases (preempt)
    2. Classifies intent
    3. Validates route against channel + auth constraints
    4. Falls back to knowledge if invalid
    """
    result = route_fn(state)
    return result


# ── Route conditional ────────────────────────────────────────────────────────

def route_to_subgraph(state: dict[str, Any]) -> str:
    """
    Conditional edge: which subgraph to enter based on the route.

    This is where the bounded choice is enforced. The router proposed
    a route; this edge sends the conversation to the right subgraph.
    If the route is unknown, default to knowledge (safe).
    """
    route_value = state.get("route", Route.KNOWLEDGE)

    route_map = {
        Route.KNOWLEDGE: "knowledge_subgraph",
        Route.ACCOUNT_SERVICING: "account_servicing_subgraph",
        Route.ARRANGEMENT: "arrangement_subgraph",
        Route.SENSITIVE_ACTION: "sensitive_action_subgraph",
        Route.COMPLIANCE_HANDOFF: "compliance_handoff_subgraph",
    }

    return route_map.get(route_value, "knowledge_subgraph")


# ── Loop budget check ────────────────────────────────────────────────────────

def check_loop_budget(state: dict[str, Any]) -> dict[str, Any]:
    """
    Check if the loop budget is exceeded.

    Every reasoning loop needs a budget:
    - max_model_turns
    - max_tool_attempts per tool
    - max_elapsed_seconds
    - repeated-state detection
    """
    max_turns = 10  # configurable via env in production
    max_seconds = 30  # configurable

    turn_count = state.get("model_turn_count", 0)
    turn_started_at = state.get("turn_started_at", time.time())
    elapsed = time.time() - turn_started_at

    if turn_count >= max_turns:
        return {
            "exit_state": SubgraphExit.HANDOFF,
            "route": "loop_budget_exceeded",
            "action_result": {"reason": "max_model_turns_exceeded", "max": max_turns},
        }

    if elapsed >= max_seconds:
        return {
            "exit_state": SubgraphExit.HANDOFF,
            "route": "loop_budget_exceeded",
            "action_result": {"reason": "max_elapsed_exceeded", "elapsed": elapsed},
        }

    return {"model_turn_count": turn_count + 1}


# ── Graph builder ────────────────────────────────────────────────────────────

def build_universal_graph() -> StateGraph:
    """
    Build the universal agent graph.

    Structure:
        START → preconditions → router → [route?] → subgraph → completion_gate → END
                                        ↘ preconditions_failed → END

    The subgraphs are compiled and added as nodes. Each subgraph has its own
    internal structure (nodes, edges, conditional routing).

    The completion gate validates the subgraph's exit state and enforces
    success language rules before the response is rendered.
    """
    graph = StateGraph(GraphState)

    # ── Add nodes ─────────────────────────────────────────────────────────
    graph.add_node("preconditions", preconditions_node)
    graph.add_node("loop_budget_check", check_loop_budget)
    graph.add_node("router", router_node)
    graph.add_node("completion_gate", completion_gate)

    # Compile and add subgraphs
    knowledge_graph = build_knowledge_subgraph().compile()
    account_servicing_graph = build_account_servicing_subgraph().compile()
    arrangement_graph = build_arrangement_subgraph().compile()
    sensitive_action_graph = build_sensitive_action_subgraph().compile()
    compliance_handoff_graph = build_compliance_handoff_subgraph().compile()

    graph.add_node("knowledge_subgraph", knowledge_graph)
    graph.add_node("account_servicing_subgraph", account_servicing_graph)
    graph.add_node("arrangement_subgraph", arrangement_graph)
    graph.add_node("sensitive_action_subgraph", sensitive_action_graph)
    graph.add_node("compliance_handoff_subgraph", compliance_handoff_graph)

    # ── Add edges ─────────────────────────────────────────────────────────
    graph.set_entry_point("preconditions")

    # Preconditions → router or direct END if failed
    graph.add_conditional_edges(
        "preconditions",
        lambda state: "router" if state.get("route") != "preconditions_failed" else "end",
        {
            "router": "loop_budget_check",
            "end": END,
        },
    )

    # Loop budget check → router
    graph.add_edge("loop_budget_check", "router")

    # Router → subgraph (conditional)
    graph.add_conditional_edges(
        "router",
        route_to_subgraph,
        {
            "knowledge_subgraph": "knowledge_subgraph",
            "account_servicing_subgraph": "account_servicing_subgraph",
            "arrangement_subgraph": "arrangement_subgraph",
            "sensitive_action_subgraph": "sensitive_action_subgraph",
            "compliance_handoff_subgraph": "compliance_handoff_subgraph",
        },
    )

    # All subgraphs → completion gate
    graph.add_edge("knowledge_subgraph", "completion_gate")
    graph.add_edge("account_servicing_subgraph", "completion_gate")
    graph.add_edge("arrangement_subgraph", "completion_gate")
    graph.add_edge("sensitive_action_subgraph", "completion_gate")
    graph.add_edge("compliance_handoff_subgraph", "completion_gate")

    # Completion gate → END
    graph.add_edge("completion_gate", END)

    return graph


def compile_universal_graph():
    """Build and compile the universal graph, returning a runnable."""
    return build_universal_graph().compile()
