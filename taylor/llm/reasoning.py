"""
LLM reasoning engine.

Handles the agent loop:
  1. Get visible tools for the current state + channel
  2. Call the LLM with system prompt + user message + tool schemas
  3. If the LLM returns tool calls, execute them through the registry
  4. Feed results back to the LLM
  5. Repeat up to max_tool_attempts
  6. Return the final response + exit state + action status

The LLM proposes. The registry executes. The completion gate validates.
This module is the bridge between nondeterministic reasoning and
deterministic safety boundaries.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from taylor.graphs.universal.state import (
    ActionStatus,
    AuthLevel,
    Channel,
    SubgraphExit,
)
from taylor.llm.client import LLMClient
from taylor.llm.prompts import get_system_prompt
from taylor.tools.envelope import ToolEnvelope, ToolResult
from taylor.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class ReasoningEngine:
    """
    Runs the LLM + tool call loop for a single subgraph invocation.

    The engine is given:
      - The route (which subgraph we're in)
      - The current state (for tool visibility and envelope construction)
      - The tool registry (for execution)
      - The LLM client

    The engine returns:
      - The LLM's text response
      - The exit state (based on what happened)
      - The action status (if any action was taken)
      - The action result (if any)
    """

    def __init__(
        self,
        llm_client: LLMClient,
        registry: ToolRegistry,
        max_tool_attempts: int = 5,
    ):
        self._llm = llm_client
        self._registry = registry
        self._max_tool_attempts = max_tool_attempts

    async def reason(
        self,
        utterance: str,
        route: str,
        state: dict[str, Any],
        conversation_history: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """
        Run the reasoning loop for this subgraph.

        Returns:
            {
                "reply": str,                    # LLM's text response
                "exit_state": SubgraphExit,      # determined exit state
                "action_status": ActionStatus | None,
                "action_result": dict | None,    # tool result if action taken
                "tool_calls_made": list,         # log of tool calls
                "usage": dict | None,            # token usage
            }
        """
        channel = state.get("channel", Channel.SMS)
        if isinstance(channel, Channel):
            channel = channel.value

        auth_level = state.get("auth_level", AuthLevel.ANONYMOUS)
        account_id = state.get("account_id")

        # Get visible tools for this state + channel
        visible_tools = self._registry.get_visible_tools(state, channel)
        tool_schemas = [t.to_openai_schema() for t in visible_tools]
        tool_names = [t.name for t in visible_tools]

        logger.info(f"Reasoning on route '{route}' with tools: {tool_names}")

        # Build system prompt
        system_prompt = get_system_prompt(route, auth_level, channel, account_id)

        # Run the LLM + tool call loop
        tool_calls_made: list[dict[str, Any]] = []
        action_result: dict[str, Any] | None = None
        action_status: ActionStatus | None = None
        messages: list[dict[str, Any]] = list(conversation_history or [])

        current_user_content = utterance
        attempts = 0

        while attempts <= self._max_tool_attempts:
            attempts += 1

            # Call LLM
            llm_result = await self._llm.chat_with_tools(
                system_prompt=system_prompt,
                user_message=current_user_content,
                tools=tool_schemas if tool_schemas else None,
                conversation_history=messages if attempts > 1 else None,
            )

            # Check for error
            if llm_result.get("error"):
                return {
                    "reply": llm_result["content"],
                    "exit_state": SubgraphExit.HANDOFF,
                    "action_status": None,
                    "action_result": None,
                    "tool_calls_made": tool_calls_made,
                    "usage": llm_result.get("usage"),
                }

            # If no tool calls, we're done — LLM gave a text response
            if not llm_result.get("tool_calls"):
                exit_state = self._determine_exit_state(route, action_status, action_result, llm_result["content"])

                return {
                    "reply": llm_result["content"] or "I'm here to help. Could you tell me more?",
                    "exit_state": exit_state,
                    "action_status": action_status,
                    "action_result": action_result,
                    "tool_calls_made": tool_calls_made,
                    "usage": llm_result.get("usage"),
                }

            # Process tool calls
            tool_calls = llm_result["tool_calls"]
            tool_results_for_llm: list[dict[str, Any]] = []

            # Add the assistant message with tool calls to conversation
            messages.append({"role": "assistant", "content": llm_result.get("content") or ""})

            for tc in tool_calls:
                tool_name = tc["name"]
                tool_args = tc["arguments"]

                logger.info(f"Tool call requested: {tool_name} with args: {tool_args}")

                # Build the tool envelope with server-derived fields
                envelope = self._build_envelope(
                    tool_name=tool_name,
                    tool_args=tool_args,
                    state=state,
                )

                # Execute through the registry (the security boundary)
                result: ToolResult = await self._registry.invoke(tool_name, envelope, state)

                tool_calls_made.append({
                    "tool": tool_name,
                    "args": tool_args,
                    "status": result.status,
                    "action_id": envelope.action_id,
                })

                # Track action status for sensitive actions
                if route == "sensitive_action" and tool_name in ("schedule_payment", "update_phone_number"):
                    if result.status == "confirmed":
                        action_status = ActionStatus.CONFIRMED
                        action_result = {
                            "status": result.status,
                            "confirmation_id": result.confirmation_id,
                            "provider_request_id": result.provider_request_id,
                            "data": result.data,
                        }
                    elif result.status == "unknown":
                        action_status = ActionStatus.UNKNOWN
                        action_result = {
                            "status": result.status,
                            "message": "Payment submission timed out. Reconciliation required.",
                        }
                    elif result.status == "rejected":
                        action_status = ActionStatus.REJECTED
                        action_result = {
                            "status": result.status,
                            "error": result.error,
                            "data": result.data,
                        }
                    elif result.status == "invalid_request":
                        action_status = ActionStatus.REJECTED
                        action_result = {
                            "status": result.status,
                            "error": result.error,
                        }

                # Also track for arrangement route (proposal results)
                if route == "arrangement" and tool_name == "validate_payment_proposal":
                    action_result = {
                        "status": result.status,
                        "data": result.data,
                    }
                    if result.status == "confirmed":
                        if result.data.get("valid"):
                            action_status = ActionStatus.VALIDATED
                        else:
                            action_status = ActionStatus.REJECTED

                # Build tool result message for the LLM
                tool_result_content = json.dumps({
                    "status": result.status,
                    "data": result.data,
                    "error": result.error,
                    "confirmation_id": result.confirmation_id,
                })

                tool_results_for_llm.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": tool_result_content,
                })

            # Feed tool results back to the LLM
            messages.extend(tool_results_for_llm)

            # Next iteration: the LLM will see the tool results and either
            # make more tool calls or generate a final text response
            current_user_content = ""  # The tool results are in the messages

        # Exceeded max tool attempts — return what we have
        logger.warning(f"Exceeded max tool attempts ({self._max_tool_attempts})")
        exit_state = self._determine_exit_state(route, action_status, action_result, "")

        return {
            "reply": "I've done what I can with the available tools. Is there anything else I can help with?",
            "exit_state": exit_state,
            "action_status": action_status,
            "action_result": action_result,
            "tool_calls_made": tool_calls_made,
            "usage": None,
        }

    def _build_envelope(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        state: dict[str, Any],
    ) -> ToolEnvelope:
        """
        Build the tool envelope with server-derived fields.

        The model supplies the intent (amount, date, method_token).
        The server supplies identity (customer_id, auth_level, account_id).
        """
        # Extract model-supplied intent fields
        amount = tool_args.get("amount")
        date_value = tool_args.get("date")
        method_token = tool_args.get("method_token")
        operation = tool_args.get("operation")
        extra = {k: v for k, v in tool_args.items()
                 if k not in ("amount", "date", "method_token", "operation")}

        # Get authorization ref from state if available
        auth_artifact = state.get("authorization_artifact")
        auth_ref = auth_artifact.get("artifact_id") if auth_artifact else None

        return ToolEnvelope.create(
            conversation_id=state.get("conversation_id", "unknown"),
            turn_id=state.get("turn_id", "unknown"),
            customer_id=state.get("customer_id", "unknown"),
            auth_level=state.get("auth_level", AuthLevel.ANONYMOUS),
            account_id=state.get("account_id"),
            intent_type=tool_name,
            amount=amount,
            date_value=date_value,
            method_token=method_token,
            operation=operation,
            authorization_ref=auth_ref,
        )

    def _determine_exit_state(
        self,
        route: str,
        action_status: ActionStatus | None,
        action_result: dict[str, Any] | None,
        reply_text: str,
    ) -> SubgraphExit:
        """
        Determine the exit state based on what happened during reasoning.

        This maps the action status and LLM response to a SubgraphExit
        that the completion gate will validate.
        """
        if route == "sensitive_action":
            if action_status == ActionStatus.CONFIRMED:
                return SubgraphExit.CONFIRMED
            elif action_status == ActionStatus.UNKNOWN:
                return SubgraphExit.UNKNOWN_RECONCILING
            elif action_status == ActionStatus.REJECTED:
                return SubgraphExit.REJECTED
            elif action_status is None:
                # No action was taken — might be asking for more info
                return SubgraphExit.CANCELLED
            return SubgraphExit.UNKNOWN_RECONCILING

        if route == "arrangement":
            if action_status == ActionStatus.VALIDATED:
                return SubgraphExit.VALIDATED_PROPOSAL
            elif action_status == ActionStatus.REJECTED:
                return SubgraphExit.INVALID_PROPOSAL
            return SubgraphExit.VALIDATED_PROPOSAL  # Default if no action taken

        if route == "account_servicing":
            if action_result and action_result.get("status") == "confirmed":
                return SubgraphExit.FRESH_RESULT
            if "transfer" in (reply_text or "").lower():
                return SubgraphExit.HANDOFF
            return SubgraphExit.FRESH_RESULT

        if route == "compliance_handoff":
            if action_result and action_result.get("status") == "confirmed":
                return SubgraphExit.TRANSFER_ACCEPTED
            return SubgraphExit.POLICY_ALLOW

        if route == "knowledge":
            if action_result and action_result.get("data", {}).get("results"):
                return SubgraphExit.CITED_ANSWER
            if "transfer" in (reply_text or "").lower() or "agent" in (reply_text or "").lower():
                return SubgraphExit.NO_ANSWER
            return SubgraphExit.CITED_ANSWER  # Default — LLM gave an answer

        return SubgraphExit.HANDOFF  # Safe default


# Need json import for tool result serialization
import json  # noqa: E402
