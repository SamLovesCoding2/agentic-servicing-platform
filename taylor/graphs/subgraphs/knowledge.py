"""
Knowledge subgraph.

Read-only retrieval. Answers FAQs and policy questions with citations.
Cannot write any state except an answer draft and citations.

Contract:
  - Allowed inputs: sanitized question, locale
  - Writable state: answer draft, citations
  - Tool authority: read-only retrieval (search_faq)
  - Required exits: cited_answer, no_answer
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, StateGraph
from pydantic import BaseModel

from taylor.graphs.universal.state import GraphState, SubgraphExit


class KnowledgeResult(BaseModel):
    exit_state: SubgraphExit
    answer: str
    citations: list[dict[str, str]] = []


def retrieve_node(state: dict[str, Any]) -> dict[str, Any]:
    """
    Retrieval node. Calls the search_faq tool to find relevant answers.
    In production, this would use vector search over a knowledge base.
    """
    # The actual tool invocation would happen here via the registry.
    # For the graph structure, we just mark the route and exit state.
    # The turn coordinator handles actual tool execution.
    return {
        "route": "knowledge",
        "exit_state": SubgraphExit.CITED_ANSWER,
    }


def no_answer_node(state: dict[str, Any]) -> dict[str, Any]:
    """Handle the case where no relevant FAQ entries are found."""
    return {
        "exit_state": SubgraphExit.NO_ANSWER,
    }


def should_answer(state: dict[str, Any]) -> str:
    """Conditional edge: do we have an answer or not?"""
    exit_state = state.get("exit_state")
    if exit_state == SubgraphExit.CITED_ANSWER:
        return "answer"
    return "no_answer"


def build_knowledge_subgraph() -> StateGraph:
    """
    Build the knowledge subgraph.

    Structure:
        retrieve → [has_answer?] → answer → END
                              → no_answer → END
    """
    graph = StateGraph(GraphState)

    graph.add_node("retrieve", retrieve_node)
    graph.add_node("no_answer", no_answer_node)

    graph.set_entry_point("retrieve")
    graph.add_conditional_edges(
        "retrieve",
        should_answer,
        {
            "answer": END,
            "no_answer": "no_answer",
        },
    )
    graph.add_edge("no_answer", END)

    return graph


# ── Contract ─────────────────────────────────────────────────────────────────

KNOWLEDGE_CONTRACT = {
    "name": "knowledge",
    "allowed_inputs": ["utterance", "locale"],
    "writable_state": ["exit_state", "route"],
    "tool_authority": ["read"],
    "required_exits": [SubgraphExit.CITED_ANSWER, SubgraphExit.NO_ANSWER],
}
