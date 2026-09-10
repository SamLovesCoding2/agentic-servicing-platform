"""
Proposal tools — calculate quotes, plans, eligibility. No side effects.

These tools compute and validate without creating any state changes.
They return normalized proposals that must be authorized before execution.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
from pydantic import BaseModel, Field

from taylor.tools.base import ProposalTool
from taylor.tools.envelope import ToolEnvelope, ToolPrecondition, ToolResult


class CalculatePayoffQuoteTool(ProposalTool):
    """Compute payoff amount for a given date."""

    def __init__(self, fac_api_base_url: str, timeout: float = 10.0):
        super().__init__(
            name="calculate_payoff_quote",
            description="Calculate the payoff amount for the customer's contract as of a specific date. Returns a quote, not a payment.",
        )
        self._fac_api_base_url = fac_api_base_url
        self._timeout = timeout

    def _parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "The date to calculate payoff for (YYYY-MM-DD). Defaults to today.",
                },
            },
            "required": [],
        }

    async def execute(self, envelope: ToolEnvelope, state: dict[str, Any]) -> ToolResult:
        account_id = envelope.actor.account_id
        if not account_id:
            return ToolResult(
                action_id=envelope.action_id,
                status="invalid_request",
                error="No account ID in authenticated session",
            )

        # Fetch balance
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(f"{self._fac_api_base_url}/accounts/{account_id}/overview")
            resp.raise_for_status()
            overview = resp.json()

        balance = Decimal(overview["balance"])
        payoff_date = envelope.intent.date or date.today()

        # Simple payoff calculation: balance + estimated interest for days remaining
        # In production, this would call the FAC API's payoff endpoint
        daily_interest_rate = Decimal("0.0001")  # ~3.65% APR
        days_to_payoff = (payoff_date - date.today()).days
        if days_to_payoff < 0:
            days_to_payoff = 0

        estimated_interest = balance * daily_interest_rate * Decimal(days_to_payoff)
        payoff_amount = balance + estimated_interest

        return ToolResult(
            action_id=envelope.action_id,
            status="confirmed",
            data={
                "payoff_amount": str(payoff_amount.quantize(Decimal("0.01"))),
                "payoff_date": payoff_date.isoformat(),
                "principal_balance": str(balance),
                "estimated_interest": str(estimated_interest.quantize(Decimal("0.01"))),
                "freshness": "computed_from_live_read",
                "computed_at": datetime.utcnow().isoformat(),
                "note": "This is a quote, not a payment. No funds have been charged.",
            },
        )


class ValidatePaymentProposalTool(ProposalTool):
    """
    Validate a payment proposal against business rules.
    Returns a normalized proposal or a rejection with reasons.
    Does NOT create a payment or charge anything.
    """

    def __init__(self, fac_api_base_url: str, timeout: float = 10.0):
        super().__init__(
            name="validate_payment_proposal",
            description="Validate a proposed payment (amount, date, method). Returns a normalized proposal or explains why it's invalid. Does NOT charge anything.",
        )
        self._fac_api_base_url = fac_api_base_url
        self._timeout = timeout

    def _parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "amount": {
                    "type": "string",
                    "description": "Payment amount in dollars (e.g., '300.00').",
                },
                "date": {
                    "type": "string",
                    "description": "Payment date (YYYY-MM-DD).",
                },
                "method_token": {
                    "type": "string",
                    "description": "Opaque token for the payment method to use.",
                },
            },
            "required": ["amount", "date", "method_token"],
        }

    async def execute(self, envelope: ToolEnvelope, state: dict[str, Any]) -> ToolResult:
        account_id = envelope.actor.account_id
        if not account_id:
            return ToolResult(
                action_id=envelope.action_id,
                status="invalid_request",
                error="No account ID in authenticated session",
            )

        amount = envelope.intent.amount
        payment_date = envelope.intent.date
        method_token = envelope.intent.method_token

        if not amount or not payment_date or not method_token:
            return ToolResult(
                action_id=envelope.action_id,
                status="invalid_request",
                error="Amount, date, and method_token are all required",
            )

        # Fetch account data for validation
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            overview_resp = await client.get(f"{self._fac_api_base_url}/accounts/{account_id}/overview")
            overview_resp.raise_for_status()
            overview = overview_resp.json()

            payments_resp = await client.get(f"{self._fac_api_base_url}/accounts/{account_id}/payments")
            payments_resp.raise_for_status()
            payments = payments_resp.json()

            rules_resp = await client.get(f"{self._fac_api_base_url}/accounts/{account_id}/negotiation_rules")
            rules_resp.raise_for_status()
            rules = rules_resp.json()

        # Validate method token exists
        valid_tokens = [m["method_token"] for m in payments.get("saved_methods", [])]
        if method_token not in valid_tokens:
            return ToolResult(
                action_id=envelope.action_id,
                status="rejected",
                data={
                    "valid": False,
                    "reason": "invalid_method_token",
                    "message": "The selected payment method is not valid for this account.",
                },
            )

        # Validate amount >= minimum
        min_payment = Decimal(rules.get("min_payment", "0"))
        if amount < min_payment:
            return ToolResult(
                action_id=envelope.action_id,
                status="rejected",
                data={
                    "valid": False,
                    "reason": "amount_below_minimum",
                    "message": f"Minimum payment is ${min_payment}.",
                    "minimum": str(min_payment),
                },
            )

        # Validate date is not in the past
        if payment_date < date.today():
            return ToolResult(
                action_id=envelope.action_id,
                status="rejected",
                data={
                    "valid": False,
                    "reason": "date_in_past",
                    "message": "Payment date cannot be in the past.",
                },
            )

        # Validate date is within settlement window (if charge-off)
        if overview.get("status") == "charge_off":
            window_days = int(rules.get("settlement_window_days", 90))
            max_date = date.today() + timedelta(days=window_days)
            if payment_date > max_date:
                return ToolResult(
                    action_id=envelope.action_id,
                    status="rejected",
                    data={
                        "valid": False,
                        "reason": "date_outside_window",
                        "message": f"For charge-off accounts, payment date must be within {window_days} days.",
                        "max_date": max_date.isoformat(),
                    },
                )

        # Normalized proposal — validated and ready for authorization
        return ToolResult(
            action_id=envelope.action_id,
            status="confirmed",
            data={
                "valid": True,
                "normalized_proposal": {
                    "amount": str(amount.quantize(Decimal("0.01"))),
                    "date": payment_date.isoformat(),
                    "method_token": method_token,
                    "account_id": account_id,
                    "account_balance": overview["balance"],
                    "remaining_after_payment": str(
                        (Decimal(overview["balance"]) - amount).quantize(Decimal("0.01"))
                    ),
                },
                "message": "Proposal is valid. Customer must authorize before execution.",
                "note": "This is a validated proposal, NOT a payment. No funds have been charged.",
            },
        )
