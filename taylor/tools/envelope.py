"""
Tool envelope contract.

Every tool invocation carries a structured envelope, not free-form arguments.
The envelope enforces the core security invariant:
  - Server-derived fields (identity, authority) cannot be overridden by model input.
  - Model-supplied fields are limited to business intent (amount, date, method token).
"""

from __future__ import annotations

from datetime import date as date_type
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


class ToolClass(str, Enum):
    READ = "read"
    PROPOSAL = "proposal"
    EXECUTION = "execution"


class ToolActor(BaseModel):
    """Server-derived. The model cannot supply these."""
    customer_id: str = Field(..., description="Server-derived from authenticated session")
    auth_level: str = Field(..., description="Server-derived: anonymous, verified, step_up")
    account_id: str | None = Field(None, description="Server-derived account reference")

    def requires_step_up(self) -> bool:
        return self.auth_level != "step_up"


class ToolIntent(BaseModel):
    """Model-supplied. Limited to business intent, not identity or authority."""
    type: str = Field(..., description="Action type: schedule_payment, update_phone, etc.")
    amount: Decimal | None = Field(None, description="Payment amount as decimal string")
    date: date_type | None = Field(None, description="Payment or action date")
    method_token: str | None = Field(None, description="Opaque payment method token")
    operation: str | None = Field(None, description="Requested operation for non-payment tools")
    extra: dict[str, Any] = Field(default_factory=dict, description="Additional model-supplied fields")

    @model_validator(mode="after")
    def validate_amount_format(self) -> ToolIntent:
        """Amounts use Decimal, not binary floating point."""
        if self.amount is not None:
            # Ensure we're using decimal, not float
            if isinstance(self.amount, float):
                raise ValueError("Amount must be Decimal, not float")
        return self


class ToolEnvelope(BaseModel):
    """
    The complete tool invocation envelope.

    Server-derived fields are populated by the turn coordinator from
    the authenticated session. Model-supplied fields come from the
    model's structured output. The registry validates that model output
    cannot overwrite server-derived fields.
    """
    conversation_id: str = Field(..., description="Server-derived")
    turn_id: str = Field(..., description="Server-derived")
    action_id: str = Field(..., description="Idempotency key, generated before external call")
    actor: ToolActor = Field(..., description="Server-derived identity and authority")
    intent: ToolIntent = Field(..., description="Model-supplied business intent")
    authorization_ref: str | None = Field(None, description="Versioned consent artifact ID")
    policy_context_version: str | None = Field(None, description="Policy snapshot identifier")

    @staticmethod
    def create(
        conversation_id: str,
        turn_id: str,
        customer_id: str,
        auth_level: str,
        account_id: str | None = None,
        intent_type: str = "unknown",
        amount: str | None = None,
        date_value: date_type | None = None,
        method_token: str | None = None,
        operation: str | None = None,
        authorization_ref: str | None = None,
        policy_context_version: str | None = None,
    ) -> ToolEnvelope:
        """Factory method for the turn coordinator to create envelopes."""
        return ToolEnvelope(
            conversation_id=conversation_id,
            turn_id=turn_id,
            action_id=str(uuid4()),
            actor=ToolActor(
                customer_id=customer_id,
                auth_level=auth_level,
                account_id=account_id,
            ),
            intent=ToolIntent(
                type=intent_type,
                amount=Decimal(amount) if amount else None,
                date=date_value,
                method_token=method_token,
                operation=operation,
            ),
            authorization_ref=authorization_ref,
            policy_context_version=policy_context_version,
        )


class ToolResult(BaseModel):
    """Result returned by a tool invocation."""
    action_id: str
    status: str  # confirmed, rejected, retryable_failure, unknown, invalid_request
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    provider_request_id: str | None = None
    confirmation_id: str | None = None

    @property
    def is_success(self) -> bool:
        return self.status == "confirmed"

    @property
    def is_unknown(self) -> bool:
        return self.status == "unknown"


# ── Tool precondition ───────────────────────────────────────────────────────

class ToolPrecondition(BaseModel):
    """A precondition that must be satisfied before a tool is visible to the model."""
    field: str  # state field to check
    operator: str  # eq, ne, in, not_null, is_null, gte, lte
    value: Any = None

    def evaluate(self, state: dict[str, Any]) -> bool:
        actual = state.get(self.field)
        if self.operator == "eq":
            return actual == self.value
        elif self.operator == "ne":
            return actual != self.value
        elif self.operator == "in":
            return actual in self.value
        elif self.operator == "not_null":
            return actual is not None
        elif self.operator == "is_null":
            return actual is None
        elif self.operator == "gte":
            return actual is not None and actual >= self.value
        elif self.operator == "lte":
            return actual is not None and actual <= self.value
        return False
