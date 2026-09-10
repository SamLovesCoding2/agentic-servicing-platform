"""
Tool registry with capability-based exposure.

The registry enforces:
  1. Tool classification (read, proposal, execution)
  2. Capability-based exposure: execution tools are hidden from the model
     until their preconditions are satisfied.
  3. Server-derived fields in the envelope cannot be overridden by model input.

The registry is the security boundary between the model's proposed actions
and the system's authorized actions.
"""

from __future__ import annotations

import logging
from typing import Any

from taylor.tools.base import BaseTool, ExecutionTool
from taylor.tools.envelope import ToolClass, ToolEnvelope, ToolResult

logger = logging.getLogger(__name__)


class ToolRegistry:
    """
    Registry of all available tools.

    Tools are registered with a name, class, and optional preconditions.
    The registry exposes tools to the model based on the current state:
    - Read tools are always available (once authenticated)
    - Proposal tools are available when preconditions are met
    - Execution tools are HIDDEN until preconditions are met
    """

    def __init__(self):
        self._tools: dict[str, BaseTool] = {}
        self._channel_overrides: dict[str, set[str]] = {}  # channel -> allowed tool names

    def register(self, tool: BaseTool) -> None:
        """Register a tool."""
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool
        logger.info(f"Registered tool: {tool.name} (class={tool.tool_class.value})")

    def set_channel_tools(self, channel: str, tool_names: set[str]) -> None:
        """
        Restrict the tool surface for a specific channel.
        Only the named tools will be visible for that channel.
        """
        self._channel_overrides[channel] = tool_names

    def get_visible_tools(self, state: dict[str, Any], channel: str | None = None) -> list[BaseTool]:
        """
        Get the list of tools visible to the model for the current state.

        Rules:
        - Read tools: always visible (if authenticated)
        - Proposal tools: visible if preconditions are met
        - Execution tools: visible ONLY if preconditions are met
        - Channel override: if set, only tools in the override set are visible
        """
        channel_filter = self._channel_overrides.get(channel) if channel else None

        visible = []
        for tool in self._tools.values():
            # Channel filter
            if channel_filter is not None and tool.name not in channel_filter:
                continue

            # Capability-based exposure
            if tool.tool_class == ToolClass.EXECUTION:
                if not tool.preconditions_met(state):
                    continue
            elif tool.tool_class == ToolClass.PROPOSAL:
                if not tool.preconditions_met(state):
                    continue
            # Read tools are always visible

            visible.append(tool)

        return visible

    def get_openai_schemas(self, state: dict[str, Any], channel: str | None = None) -> list[dict[str, Any]]:
        """Get OpenAI function-calling schemas for visible tools."""
        return [tool.to_openai_schema() for tool in self.get_visible_tools(state, channel)]

    def get_tool(self, name: str) -> BaseTool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    async def invoke(
        self,
        tool_name: str,
        envelope: ToolEnvelope,
        state: dict[str, Any],
    ) -> ToolResult:
        """
        Invoke a tool by name.

        Validates:
        1. Tool exists
        2. Tool is visible for the current state (preconditions met)
        3. For execution tools: authorization is present and valid

        This is the single execution boundary. All tool calls go through here.
        """
        tool = self._tools.get(tool_name)
        if not tool:
            return ToolResult(
                action_id=envelope.action_id,
                status="invalid_request",
                error=f"Unknown tool: {tool_name}",
            )

        # Check visibility (preconditions)
        if not tool.preconditions_met(state):
            return ToolResult(
                action_id=envelope.action_id,
                status="invalid_request",
                error=f"Tool preconditions not met: {tool_name}",
            )

        # For execution tools, validate authorization
        if isinstance(tool, ExecutionTool):
            auth_error = tool.validate_authorization(envelope)
            if auth_error is not None:
                return auth_error

        logger.info(
            f"Invoking tool: {tool_name} action_id={envelope.action_id} "
            f"class={tool.tool_class.value} intent={envelope.intent.type}"
        )

        try:
            result = await tool.execute(envelope, state)
            logger.info(
                f"Tool result: {tool_name} action_id={envelope.action_id} "
                f"status={result.status}"
            )
            return result
        except Exception as e:
            logger.exception(f"Tool execution failed: {tool_name}")
            return ToolResult(
                action_id=envelope.action_id,
                status="retryable_failure",
                error=f"Tool execution failed: {e}",
            )

    def all_tool_names(self) -> list[str]:
        """Get all registered tool names."""
        return list(self._tools.keys())
