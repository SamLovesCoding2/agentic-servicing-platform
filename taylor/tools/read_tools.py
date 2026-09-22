"""
Read tools — retrieve facts, no side effects.

These tools fetch data from the mock FAC API and mock knowledge base.
All return data with a freshness label.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx
from pydantic import BaseModel, Field

from taylor.tools.base import ReadTool
from taylor.tools.envelope import ToolEnvelope, ToolResult

# ── Mock knowledge base ──────────────────────────────────────────────────────

MOCK_FAQ: list[dict[str, str]] = [
    {
        "question": "What happens if I miss a payment?",
        "answer": "If you miss a payment, contact us as soon as possible. We may be able to arrange a payment plan or move your due date.",
        "category": "payments",
    },
    {
        "question": "Can I change my due date?",
        "answer": "Yes, you may be eligible to change your due date. Please speak with a representative to discuss your options.",
        "category": "account",
    },
    {
        "question": "How do I set up AutoPay?",
        "answer": "You can set up AutoPay through your online portal or by calling us. You'll need a saved payment method.",
        "category": "payments",
    },
    {
        "question": "What is a charge-off?",
        "answer": "A charge-off occurs when an account is significantly past due. It does not eliminate your obligation to pay.",
        "category": "account",
    },
    {
        "question": "Can I settle my contract for less than the full balance?",
        "answer": "Settlement options may be available depending on your account status and circumstances. Contact us to discuss.",
        "category": "settlement",
    },
]


# ── Response models ──────────────────────────────────────────────────────────

class AccountOverviewResult(BaseModel):
    balance: str
    due_date: str
    status: str
    days_past_due: int
    last_payment: str
    last_payment_amount: str
    collateral: str
    fetched_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


# ── Tools ────────────────────────────────────────────────────────────────────


class GetAccountOverviewTool(ReadTool):
    """Fetch account overview (balance, due date, status) from FAC API."""

    def __init__(self, fac_api_base_url: str, timeout: float = 10.0):
        super().__init__(
            name="get_account_overview",
            description="Get the customer's account overview including balance, due date, and status.",
        )
        self._fac_api_base_url = fac_api_base_url
        self._timeout = timeout

    def _parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
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

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(f"{self._fac_api_base_url}/accounts/{account_id}/overview")
            resp.raise_for_status()
            data = resp.json()

        data["fetched_at"] = datetime.utcnow().isoformat()
        data["freshness"] = "live_read"

        return ToolResult(
            action_id=envelope.action_id,
            status="confirmed",
            data=data,
        )


class GetPaymentMethodsTool(ReadTool):
    """List saved payment methods (tokens only, never raw credentials)."""

    def __init__(self, fac_api_base_url: str, timeout: float = 10.0):
        super().__init__(
            name="get_payment_methods",
            description="List the customer's saved payment methods. Returns opaque tokens, never raw card or bank numbers.",
        )
        self._fac_api_base_url = fac_api_base_url
        self._timeout = timeout

    def _parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
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

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(f"{self._fac_api_base_url}/accounts/{account_id}/payments")
            resp.raise_for_status()
            data = resp.json()

        # Only return method tokens and display info — never raw credentials
        safe_methods = [
            {
                "method_token": m["method_token"],
                "type": m["type"],
                "last4": m.get("last4"),
                "brand": m.get("brand"),
                "expiry": m.get("expiry"),
            }
            for m in data.get("saved_methods", [])
        ]

        return ToolResult(
            action_id=envelope.action_id,
            status="confirmed",
            data={
                "saved_methods": safe_methods,
                "autopay": data.get("autopay"),
                "scheduled": data.get("scheduled"),
                "freshness": "live_read",
                "fetched_at": datetime.utcnow().isoformat(),
            },
        )


class SearchFAQTool(ReadTool):
    """Search the FAQ/knowledge base. Read-only retrieval."""

    def __init__(self):
        super().__init__(
            name="search_faq",
            description="Search the knowledge base for FAQs and policy information. Returns cited answers.",
        )

    def _parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The question or topic to search for.",
                },
            },
            "required": ["query"],
        }

    async def execute(self, envelope: ToolEnvelope, state: dict[str, Any]) -> ToolResult:
        query = envelope.intent.extra.get("query", "").lower()
        if not query:
            return ToolResult(
                action_id=envelope.action_id,
                status="invalid_request",
                error="Query is required for FAQ search",
            )

        # Simple keyword matching (in production, this would be vector search)
        results = []
        for item in MOCK_FAQ:
            if query in item["question"].lower() or query in item["answer"].lower():
                results.append({
                    "question": item["question"],
                    "answer": item["answer"],
                    "category": item["category"],
                    "citation": f"faq_{MOCK_FAQ.index(item):03d}",
                })

        if not results:
            return ToolResult(
                action_id=envelope.action_id,
                status="confirmed",
                data={
                    "results": [],
                    "message": "No matching FAQ entries found",
                    "freshness": "static_knowledge",
                },
            )

        return ToolResult(
            action_id=envelope.action_id,
            status="confirmed",
            data={
                "results": results,
                "freshness": "static_knowledge",
            },
        )
