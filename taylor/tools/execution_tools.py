"""
Execution tools — mutate state or contact provider.

These tools require:
  - Step-up authentication
  - Authorization artifact (versioned consent)
  - Policy recheck at execution time
  - Idempotency (action_id as key)
  - Authoritative confirmation persisted before success language

Hidden from the model until preconditions are satisfied.
"""

from __future__ import annotations

from typing import Any

import httpx

from taylor.tools.base import ExecutionTool
from taylor.tools.envelope import ToolEnvelope, ToolPrecondition, ToolResult


class SchedulePaymentTool(ExecutionTool):
    """
    Submit a payment to the mock payment provider.
    Requires: validated proposal, step-up auth, authorization artifact.
    Returns: confirmed, rejected, or unknown (requires reconciliation).
    """

    def __init__(
        self,
        payment_provider_base_url: str,
        fac_api_base_url: str,
        timeout: float = 10.0,
    ):
        super().__init__(
            name="schedule_payment",
            description="Submit a validated payment to the payment processor. Requires customer authorization. Returns confirmation or pending status.",
            preconditions=[
                ToolPrecondition(field="action_status", operator="eq", value="AUTHORIZED"),
            ],
        )
        self._payment_provider_base_url = payment_provider_base_url
        self._fac_api_base_url = fac_api_base_url
        self._timeout = timeout

    def _parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "amount": {"type": "string", "description": "Payment amount (e.g., '300.00')."},
                "date": {"type": "string", "description": "Payment date (YYYY-MM-DD)."},
                "method_token": {"type": "string", "description": "Opaque payment method token."},
            },
            "required": ["amount", "date", "method_token"],
        }

    async def execute(self, envelope: ToolEnvelope, state: dict[str, Any]) -> ToolResult:
        # Authorization check already done by base class, but double-check
        auth_error = self.validate_authorization(envelope)
        if auth_error is not None:
            return auth_error

        amount = envelope.intent.amount
        payment_date = envelope.intent.date
        method_token = envelope.intent.method_token
        account_id = envelope.actor.account_id

        if not all([amount, payment_date, method_token, account_id]):
            return ToolResult(
                action_id=envelope.action_id,
                status="invalid_request",
                error="Missing required fields: amount, date, method_token, account_id",
            )

        # Submit to payment provider with idempotency key (action_id)
        submission = {
            "action_id": envelope.action_id,
            "account_id": account_id,
            "amount": str(amount),
            "date": payment_date.isoformat(),
            "method_token": method_token,
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._payment_provider_base_url}/payments/submit",
                    json=submission,
                )
                resp.raise_for_status()
                result = resp.json()

            # Check for simulated timeout
            if result.get("error") == "timeout_simulated":
                return ToolResult(
                    action_id=envelope.action_id,
                    status="unknown",
                    data={"message": "Payment submission timed out. Reconciliation required."},
                    error="timeout",
                )

            return ToolResult(
                action_id=envelope.action_id,
                status=result.get("status", "unknown"),
                data=result,
                provider_request_id=result.get("provider_request_id"),
                confirmation_id=result.get("confirmation_id"),
                error=result.get("rejection_reason"),
            )

        except httpx.TimeoutException:
            # Timeout after submission — this is UNKNOWN, not failure
            return ToolResult(
                action_id=envelope.action_id,
                status="unknown",
                data={"message": "Payment submission timed out. Reconciliation required."},
                error="timeout",
            )
        except Exception as e:
            return ToolResult(
                action_id=envelope.action_id,
                status="retryable_failure",
                error=f"Payment submission failed: {e}",
            )


class UpdatePhoneNumberTool(ExecutionTool):
    """Update the customer's phone number. Requires authorization."""

    def __init__(self, fac_api_base_url: str, timeout: float = 10.0):
        super().__init__(
            name="update_phone_number",
            description="Update the customer's phone number on file. Requires customer authorization.",
            preconditions=[
                ToolPrecondition(field="action_status", operator="eq", value="AUTHORIZED"),
            ],
        )
        self._fac_api_base_url = fac_api_base_url
        self._timeout = timeout

    def _parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "phone": {"type": "string", "description": "New phone number in E.164 format."},
            },
            "required": ["phone"],
        }

    async def execute(self, envelope: ToolEnvelope, state: dict[str, Any]) -> ToolResult:
        auth_error = self.validate_authorization(envelope)
        if auth_error is not None:
            return auth_error

        account_id = envelope.actor.account_id
        new_phone = envelope.intent.extra.get("phone")

        if not new_phone:
            return ToolResult(
                action_id=envelope.action_id,
                status="invalid_request",
                error="New phone number is required",
            )

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._fac_api_base_url}/accounts/{account_id}/servicing",
                    json={"field": "phone", "value": {"phone": new_phone}},
                )
                resp.raise_for_status()
                result = resp.json()

            return ToolResult(
                action_id=envelope.action_id,
                status="confirmed",
                data=result,
            )
        except Exception as e:
            return ToolResult(
                action_id=envelope.action_id,
                status="retryable_failure",
                error=f"Phone update failed: {e}",
            )


class TransferToAgentTool(ExecutionTool):
    """Transfer the customer to a live human agent."""

    def __init__(self):
        super().__init__(
            name="transfer_to_agent",
            description="Transfer the customer to a live human agent. Use when the customer requests a human or the system cannot resolve their issue.",
            preconditions=[],  # Always available (no auth precondition — transfer is safe)
        )

    def _parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "Reason for transfer."},
            },
            "required": ["reason"],
        }

    async def execute(self, envelope: ToolEnvelope, state: dict[str, Any]) -> ToolResult:
        reason = envelope.intent.extra.get("reason", "customer_request")

        return ToolResult(
            action_id=envelope.action_id,
            status="confirmed",
            data={
                "transfer_initiated": True,
                "reason": reason,
                "transfer_id": f"XFR-{envelope.action_id[:8]}",
                "message": "Customer is being transferred to a live agent.",
            },
        )
