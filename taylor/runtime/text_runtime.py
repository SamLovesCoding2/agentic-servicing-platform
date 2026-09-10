"""
Text runtime — handles SMS and Chat text interactions.

This is the entry point for text-based conversation turns.
It creates the tool registry, configures the turn coordinator
(with optional LLM and database), and manages the session lifecycle.

Key difference from voice:
  - No streaming audio, VAD, or endpointing
  - No DTMF/protected collection (chat uses secure elements, M4+)
  - Longer turn timeout (30s vs 15s for voice)
  - Channel-specific tool surface (chat excludes payment execution)
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from taylor.graphs.universal.state import AuthLevel, Channel
from taylor.llm.client import LLMClient
from taylor.runtime.turn_coordinator import TurnCoordinator
from taylor.tools.registry import ToolRegistry
from taylor.tools.read_tools import (
    GetAccountOverviewTool,
    GetPaymentMethodsTool,
    SearchFAQTool,
)
from taylor.tools.proposal_tools import (
    CalculatePayoffQuoteTool,
    ValidatePaymentProposalTool,
)
from taylor.tools.execution_tools import (
    SchedulePaymentTool,
    TransferToAgentTool,
    UpdatePhoneNumberTool,
)

logger = logging.getLogger(__name__)


def load_graph_config(config_name: str = "default_en") -> dict[str, Any]:
    """Load a file-backed graph config. File config beats DB config and legacy code."""
    config_path = (
        Path(__file__).parent.parent / "graphs" / "universal" / "graph_configs" / f"{config_name}.json"
    )
    if not config_path.exists():
        raise FileNotFoundError(f"Graph config not found: {config_path}")
    with open(config_path) as f:
        return json.load(f)


def build_tool_registry(config: dict[str, Any]) -> ToolRegistry:
    """Build the tool registry from the graph config."""
    fac_api_url = os.environ.get("FAC_API_BASE_URL", "http://localhost:9000")
    payment_provider_url = os.environ.get("PAYMENT_PROVIDER_BASE_URL", "http://localhost:9001")
    timeout = float(os.environ.get("FAC_API_TIMEOUT_SECONDS", "10"))

    registry = ToolRegistry()

    # Read tools
    registry.register(GetAccountOverviewTool(fac_api_url, timeout))
    registry.register(GetPaymentMethodsTool(fac_api_url, timeout))
    registry.register(SearchFAQTool())

    # Proposal tools
    registry.register(CalculatePayoffQuoteTool(fac_api_url, timeout))
    registry.register(ValidatePaymentProposalTool(fac_api_url, timeout))

    # Execution tools
    registry.register(SchedulePaymentTool(payment_provider_url, fac_api_url, timeout))
    registry.register(UpdatePhoneNumberTool(fac_api_url, timeout))
    registry.register(TransferToAgentTool())

    # Apply channel overrides
    channel_overrides = config.get("channel_overrides", {})
    for channel, tool_names in channel_overrides.items():
        registry.set_channel_tools(channel, set(tool_names))

    return registry


class TextRuntime:
    """
    Runtime for text-based channels (SMS and Chat).

    Manages:
    - Tool registry (with channel-specific tool surfaces)
    - Turn coordinator (with LLM + database when available)
    - Graph config (file-backed, baked into image)
    - Conversation history (for multi-turn context)
    """

    def __init__(
        self,
        config_name: str = "default_en",
        max_turn_seconds: float | None = None,
        llm_client: LLMClient | None = None,
        database=None,
        max_tool_attempts: int = 5,
    ):
        self._config = load_graph_config(config_name)
        self._registry = build_tool_registry(self._config)

        budget = self._config.get("loop_budget", {})
        if max_turn_seconds is None:
            max_turn_seconds = float(budget.get("max_text_turn_seconds", 30))

        output_filter_config = self._config.get("output_filter", {})
        replacements = output_filter_config.get("replacements") if output_filter_config.get("enabled") else None

        # Auto-create LLM client if API key is available
        if llm_client is None and os.environ.get("OPENAI_API_KEY"):
            llm_client = LLMClient()

        self._coordinator = TurnCoordinator(
            tool_registry=self._registry,
            llm_client=llm_client,
            database=database,
            max_turn_seconds=max_turn_seconds,
            output_replacements=replacements,
            max_tool_attempts=max_tool_attempts,
        )

        # Conversation history per conversation_id
        self._history: dict[str, list[dict[str, Any]]] = {}

    @property
    def coordinator(self) -> TurnCoordinator:
        return self._coordinator

    @property
    def registry(self) -> ToolRegistry:
        return self._registry

    @property
    def config(self) -> dict[str, Any]:
        return self._config

    @property
    def has_llm(self) -> bool:
        return self._coordinator.has_llm

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
    ) -> dict[str, Any]:
        """Run a single text conversation turn with conversation history."""
        history = self._history.get(conversation_id, [])

        result = await self._coordinator.run_turn(
            utterance=utterance,
            conversation_id=conversation_id,
            customer_id=customer_id,
            auth_level=auth_level,
            channel=channel,
            account_id=account_id,
            session_state=session_state,
            business_state=business_state,
            protected_state=protected_state,
            conversation_history=history if history else None,
        )

        # Update conversation history
        history.append({"role": "user", "content": utterance})
        history.append({"role": "assistant", "content": result["reply"]})
        # Keep last 20 messages to avoid context explosion
        self._history[conversation_id] = history[-20:]

        return result

    def get_visible_tools(self, state: dict[str, Any], channel: str) -> list[str]:
        """Get the names of tools visible to the model for this state + channel."""
        tools = self._registry.get_visible_tools(state, channel)
        return [t.name for t in tools]

    def clear_history(self, conversation_id: str) -> None:
        """Clear conversation history for a session."""
        self._history.pop(conversation_id, None)
