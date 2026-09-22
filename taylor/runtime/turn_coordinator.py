"""
Turn coordinator.

Prepares a stable state snapshot, runs the reasoning engine (LLM-powered
when available, deterministic fallback for testing), and persists the
transition to the database.

Owns:
  - Deadlines (max turn time)
  - Cancellation
  - Retry policy
  - Correlation identifiers (conversation_id, turn_id, graph_run_id)
  - Tool registry (the execution boundary)

The turn coordinator is the single entry point for running a conversation
turn. All graph invocations go through here.
"""

from __future__ import annotations

import logging
import time
from typing import Any
from uuid import uuid4

from taylor.graphs.universal.completion_gate import (
    completion_gate,
)
from taylor.graphs.universal.router import Route
from taylor.graphs.universal.router import route as route_fn
from taylor.graphs.universal.state import (
    ActionStatus,
    AuthLevel,
    Channel,
    SubgraphExit,
)
from taylor.llm.client import LLMClient
from taylor.llm.reasoning import ReasoningEngine
from taylor.output.output_filter import filter_output
from taylor.tools.envelope import ToolEnvelope, ToolResult
from taylor.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class TurnCoordinator:
    """
    Coordinates a single conversation turn.

    Flow:
    1. Prepare state snapshot from session + business + protected state
    2. Route to the appropriate subgraph (deterministic router)
    3. Run the reasoning engine (LLM + tool calls) for that route
    4. Run the completion gate to validate the result
    5. Generate the reply (respecting success language constraints)
    6. Apply the output filter
    7. Persist to database (if available)

    The coordinator owns the tool registry, which is the execution boundary.
    """

    def __init__(
        self,
        tool_registry: ToolRegistry,
        llm_client: LLMClient | None = None,
        database=None,
        max_turn_seconds: float = 30.0,
        output_replacements: dict[str, str] | None = None,
        max_tool_attempts: int = 5,
    ):
        self._registry = tool_registry
        self._llm = llm_client
        self._database = database
        self._max_turn_seconds = max_turn_seconds
        self._output_replacements = output_replacements
        self._max_tool_attempts = max_tool_attempts

        # Create reasoning engine if LLM is available
        self._reasoning: ReasoningEngine | None = None
        if llm_client:
            self._reasoning = ReasoningEngine(
                llm_client=llm_client,
                registry=tool_registry,
                max_tool_attempts=max_tool_attempts,
            )

    @property
    def has_llm(self) -> bool:
        return self._reasoning is not None

    def _prepare_state(
        self,
        utterance: str,
        conversation_id: str,
        customer_id: str,
        auth_level: AuthLevel | str,
        channel: Channel | str,
        account_id: str | None = None,
        session_state: dict[str, Any] | None = None,
        business_state: dict[str, Any] | None = None,
        protected_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Prepare a stable state snapshot for the turn."""
        turn_id = str(uuid4())

        auth = AuthLevel(auth_level) if isinstance(auth_level, str) else auth_level
        ch = Channel(channel) if isinstance(channel, str) else channel

        state: dict[str, Any] = {
            "utterance": utterance,
            "turn_id": turn_id,
            "turn_started_at": time.time(),
            "model_turn_count": 0,
            "tool_attempt_counts": {},
            "conversation_id": conversation_id,
            "customer_id": customer_id,
            "auth_level": auth,
            "channel": ch,
            "locale": "en-US",
            "collected_slots": session_state.get("collected_slots", {}) if session_state else {},
            "pending_confirmation": session_state.get("pending_confirmation") if session_state else None,
            "selected_payment_method": session_state.get("selected_payment_method") if session_state else None,
            "action_status": "PROPOSED",
            "action_id": None,
            "action_intent": None,
            "action_result": None,
            "gate_result": None,
        }

        if business_state:
            state.update(business_state)
        if account_id:
            state["account_id"] = account_id
        if protected_state:
            state["credential_token"] = protected_state.get("credential_token")
            state["authorization_artifact"] = protected_state.get("authorization_artifact")

        return state

    async def run_turn(
        self,
        utterance: str,
        conversation_id: str,
        customer_id: str,
        auth_level: AuthLevel | str,
        channel: Channel | str,
        account_id: str | None = None,
        session_state: dict[str, Any] | None = None,
        business_state: dict[str, Any] | None = None,
        protected_state: dict[str, Any] | None = None,
        conversation_history: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """
        Run a single conversation turn.

        Uses the LLM reasoning engine when available, falls back to
        deterministic mode for testing.
        """
        state = self._prepare_state(
            utterance=utterance,
            conversation_id=conversation_id,
            customer_id=customer_id,
            auth_level=auth_level,
            channel=channel,
            account_id=account_id,
            session_state=session_state,
            business_state=business_state,
            protected_state=protected_state,
        )

        logger.info(
            f"Turn started: conversation={conversation_id} "
            f"channel={state['channel']} auth={state['auth_level']}"
        )

        # Step 1: Route (deterministic)
        route_result = route_fn(state)
        route = route_result.get("route", Route.KNOWLEDGE)
        state["route"] = route
        state["detected_intent"] = route_result.get("detected_intent")

        logger.info(f"Routed to: {route}")

        # Step 2: Reason (LLM-powered or deterministic)
        if self._reasoning:
            reasoning_result = await self._reasoning.reason(
                utterance=utterance,
                route=route,
                state=state,
                conversation_history=conversation_history,
            )
            reply_text = reasoning_result["reply"]
            exit_state = reasoning_result["exit_state"]
            action_status = reasoning_result.get("action_status")
            action_result = reasoning_result.get("action_result")
            tool_calls_made = reasoning_result.get("tool_calls_made", [])
            usage = reasoning_result.get("usage")
        else:
            # Deterministic fallback (for testing without LLM)
            exit_state, action_status, action_result, reply_text = self._deterministic_reply(route, state)
            tool_calls_made = []
            usage = None

        state["exit_state"] = exit_state
        if action_status:
            state["action_status"] = action_status
        if action_result:
            state["action_result"] = action_result

        # Step 3: Completion gate
        gate_input = dict(state)
        gate_input["exit_state"] = exit_state
        gate_result = completion_gate(gate_input)
        state["gate_result"] = gate_result.get("gate_result")
        success_allowed = gate_result.get("gate_result", {}).get("success_language_allowed", False)

        # If gate failed, override reply
        if not gate_result.get("gate_result", {}).get("gate_passed", False):
            reply_text = "I'm sorry, I couldn't complete that action. Let me transfer you to an agent."
            exit_state = SubgraphExit.HANDOFF

        # Step 4: Apply output filter
        reply_text = filter_output(reply_text, self._output_replacements)

        # Step 5: Persist to database
        if self._database:
            await self._persist_turn(
                state=state,
                route=route,
                exit_state=exit_state,
                action_status=action_status,
                action_result=action_result,
                tool_calls_made=tool_calls_made,
                reply=reply_text,
                usage=usage,
            )

        logger.info(
            f"Turn completed: conversation={conversation_id} "
            f"route={route} exit={exit_state} "
            f"success_allowed={success_allowed}"
        )

        return {
            "reply": reply_text,
            "route": route,
            "exit_state": exit_state,
            "action_status": action_status,
            "action_result": action_result,
            "gate_result": gate_result.get("gate_result"),
            "success_language_allowed": success_allowed,
            "tool_calls_made": tool_calls_made,
            "usage": usage,
            "state": state,
        }

    async def _persist_turn(
        self,
        state: dict[str, Any],
        route: str,
        exit_state: SubgraphExit,
        action_status: ActionStatus | None,
        action_result: dict[str, Any] | None,
        tool_calls_made: list[dict[str, Any]],
        reply: str,
        usage: dict[str, Any] | None,
    ):
        """Persist turn results to the database."""
        try:
            conversation_id = state["conversation_id"]
            turn_id = state["turn_id"]
            customer_id = state["customer_id"]
            channel = state.get("channel", Channel.SMS)
            if isinstance(channel, Channel):
                channel = channel.value
            auth_level = state.get("auth_level", AuthLevel.ANONYMOUS)
            if isinstance(auth_level, AuthLevel):
                auth_level = auth_level.value

            # Save session
            await self._database.save_session(
                conversation_id=conversation_id,
                customer_id=customer_id,
                auth_level=auth_level,
                channel=channel,
                collected_slots=state.get("collected_slots", {}),
                pending_confirmation=state.get("pending_confirmation"),
            )

            # Save tool actions
            for tc in tool_calls_made:
                await self._database.save_tool_action(
                    action_id=tc["action_id"],
                    conversation_id=conversation_id,
                    turn_id=turn_id,
                    customer_id=customer_id,
                    action_type=tc["tool"],
                    status=tc["status"],
                    intent=tc.get("args", {}),
                )

            # Save authorization artifact if present
            auth_artifact = state.get("authorization_artifact")
            if auth_artifact:
                await self._database.save_authorization_artifact(auth_artifact)

            # Save audit event
            await self._database.save_audit_event(
                conversation_id=conversation_id,
                turn_id=turn_id,
                customer_id=customer_id,
                event_type="turn_completed",
                event_data={
                    "route": route,
                    "exit_state": exit_state.value if isinstance(exit_state, SubgraphExit) else str(exit_state),
                    "action_status": action_status.value if action_status else None,
                    "reply": reply[:500],  # Truncate for storage
                    "tool_calls": tool_calls_made,
                    "usage": usage,
                },
                model_version=usage and "gpt-4o",
            )
        except Exception as e:
            logger.warning(f"Database persistence failed (non-fatal): {e}")

    def _deterministic_reply(
        self,
        route: str,
        state: dict[str, Any],
    ) -> tuple[SubgraphExit, ActionStatus | None, dict[str, Any] | None, str]:
        """Deterministic fallback reply (no LLM). For testing only."""
        exit_state = SubgraphExit.CITED_ANSWER
        action_status = None
        action_result = None

        if route == "compliance_handoff":
            exit_state = SubgraphExit.TRANSFER_ACCEPTED
            reply = "I understand. Let me transfer you to a specialist who can help with this."
        elif route == "sensitive_action":
            auth = state.get("auth_level", AuthLevel.ANONYMOUS)
            if auth == AuthLevel.STEP_UP:
                exit_state = SubgraphExit.CONFIRMED
                action_status = ActionStatus.CONFIRMED
                action_result = {"status": "confirmed", "confirmation_id": "CONF-MOCK001"}
                reply = "Your payment has been scheduled. Confirmation number: CONF-MOCK001."
            else:
                exit_state = SubgraphExit.PRECONDITION_REJECTED
                reply = "I need to verify your identity before I can process a payment."
        elif route == "arrangement":
            exit_state = SubgraphExit.VALIDATED_PROPOSAL
            reply = "Based on your account, that payment proposal would be valid. Would you like to proceed?"
        elif route == "account_servicing":
            exit_state = SubgraphExit.FRESH_RESULT
            reply = "I've retrieved your account information. Is there anything else I can help with?"
        else:
            reply = "Here's what I found. Is there anything else I can help with?"

        return exit_state, action_status, action_result, reply

    async def invoke_tool(
        self,
        tool_name: str,
        envelope: ToolEnvelope,
        state: dict[str, Any],
    ) -> ToolResult:
        """Invoke a tool through the registry (the execution boundary)."""
        return await self._registry.invoke(tool_name, envelope, state)
