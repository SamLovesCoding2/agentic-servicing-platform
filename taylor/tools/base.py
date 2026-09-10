"""
Base tool classes.

Three classes of tools with different authority levels:
  - ReadTool: retrieve facts, must describe freshness. No side effects.
  - ProposalTool: calculate quotes, plans, eligibility. No side effects.
  - ExecutionTool: mutate state or contact provider. Requires step-up auth,
    authorization artifact, policy recheck, and idempotency.

Capability-based exposure: ExecutionTools are not visible to the model
until their preconditions are satisfied. This is enforced in the registry,
not in the prompt.
"""

from __future__ import annotations

import abc
from typing import Any

from taylor.tools.envelope import (
    ToolClass,
    ToolEnvelope,
    ToolPrecondition,
    ToolResult,
)


class BaseTool(abc.ABC):
    """
    Abstract base for all tools.

    Every tool has:
      - name: unique identifier
      - tool_class: read, proposal, or execution
      - description: for the model's tool schema
      - preconditions: list of ToolPrecondition (for capability-based exposure)
      - execute: the actual logic
    """

    def __init__(
        self,
        name: str,
        tool_class: ToolClass,
        description: str,
        preconditions: list[ToolPrecondition] | None = None,
    ):
        self.name = name
        self.tool_class = tool_class
        self.description = description
        self.preconditions = preconditions or []

    def preconditions_met(self, state: dict[str, Any]) -> bool:
        """Check if all preconditions are satisfied for this tool to be visible."""
        return all(p.evaluate(state) for p in self.preconditions)

    @abc.abstractmethod
    async def execute(self, envelope: ToolEnvelope, state: dict[str, Any]) -> ToolResult:
        """Execute the tool. Must return a ToolResult."""
        ...

    def to_openai_schema(self) -> dict[str, Any]:
        """Convert to OpenAI function-calling schema."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self._parameters_schema(),
            },
        }

    def _parameters_schema(self) -> dict[str, Any]:
        """Override in subclasses to define the model-facing parameter schema."""
        return {"type": "object", "properties": {}}


class ReadTool(BaseTool):
    """
    Read tools retrieve facts and must describe freshness.
    Always available once authenticated. No side effects.
    """

    def __init__(self, name: str, description: str, preconditions: list[ToolPrecondition] | None = None):
        super().__init__(name, ToolClass.READ, description, preconditions)


class ProposalTool(BaseTool):
    """
    Proposal tools calculate quotes, dates, plans, or eligibility.
    No side effects. Available when preconditions are met.
    """

    def __init__(self, name: str, description: str, preconditions: list[ToolPrecondition] | None = None):
        super().__init__(name, ToolClass.PROPOSAL, description, preconditions)


class ExecutionTool(BaseTool):
    """
    Execution tools mutate state or contact a provider.
    Requires: step-up auth, authorization artifact, policy recheck, idempotency.
    Hidden from the model until preconditions are satisfied.
    """

    def __init__(self, name: str, description: str, preconditions: list[ToolPrecondition] | None = None):
        super().__init__(name, ToolClass.EXECUTION, description, preconditions)

    def validate_authorization(self, envelope: ToolEnvelope) -> ToolResult | None:
        """
        Validate that the envelope has proper authorization for execution.
        Returns a ToolResult with error if authorization is missing/invalid.
        """
        if envelope.actor.requires_step_up():
            return ToolResult(
                action_id=envelope.action_id,
                status="invalid_request",
                error="Step-up authentication required for execution tools",
            )

        if not envelope.authorization_ref:
            return ToolResult(
                action_id=envelope.action_id,
                status="invalid_request",
                error="Authorization artifact required for execution tools",
            )

        return None  # Authorization is valid
