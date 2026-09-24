"""Activities for the durable orchestration layer.

All I/O lives here: HTTP calls to the mock payment provider, compliance
evaluation, and best-effort audit recording. Activities are non-deterministic
by design and run inside the Temporal worker (here: in-process functions
registered with the worker, callable directly for tests).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import httpx
from temporalio import activity

from taylor.compliance.registry import default_compliance_engine
from taylor.compliance.rules import ActionContext
from taylor.orchestration.shared import PaymentArrangementResult

logger = logging.getLogger(__name__)


def _payment_provider_url() -> str:
    return os.environ.get("PAYMENT_PROVIDER_BASE_URL", "http://localhost:9001")


def _timeout() -> float:
    return float(os.environ.get("FAC_API_TIMEOUT_SECONDS", "10"))


# ── Compliance gate (fail-closed, same engine as the registry) ───────────────

@activity.defn
async def compliance_check(input_: PaymentArrangementResult | Any) -> dict[str, Any]:
    """Evaluate the arrangement against the compliance engine.

    Returns a plain dict so the workflow only sees serializable data.
    Uses the *input* object's fields; the type is Any at runtime because the
    workflow passes the arrangement input dataclass.
    """
    amount = None
    try:
        amount = Decimal(input_.amount) if getattr(input_, "amount", None) else None
    except InvalidOperation:
        amount = None

    context = ActionContext(
        action_type="schedule_payment",
        tenant=str(getattr(input_, "tenant", "westpond")),
        channel="sms",
        auth_level=str(getattr(input_, "auth_level", "step_up")),
        customer_id=str(getattr(input_, "customer_id", "")),
        account_id=getattr(input_, "account_id", None),
        amount=amount,
        scheduled_date=None,  # durable timer enforces the window; engine still checks amount/caps
        disclosures=tuple(getattr(input_, "disclosures", ()) or ()),
    )
    decision = default_compliance_engine().evaluate(context)

    return {
        "decision": decision.decision.value,
        "blocked": decision.blocked,
        "requires_step_up": decision.requires_step_up,
        "matched_rules": [m.to_dict() for m in decision.matched],
    }


# ── Provider calls (idempotent by action_id) ─────────────────────────────────

@activity.defn
async def submit_payment(input_: Any) -> dict[str, Any]:
    """Submit the payment to the provider. Never raises on a non-success
    business outcome — returns status confirmed/rejected/unknown instead."""
    payload = {
        "action_id": input_.action_id,
        "account_id": input_.account_id,
        "amount": input_.amount,
        "date": input_.scheduled_date,
        "method_token": input_.method_token,
    }
    try:
        async with httpx.AsyncClient(timeout=_timeout()) as client:
            resp = await client.post(f"{_payment_provider_url()}/payments/submit", json=payload)
            resp.raise_for_status()
            data = resp.json()
        if data.get("error") == "timeout_simulated":
            return {"status": "unknown", "message": "provider timeout — reconciliation required"}
        return {
            "status": data.get("status", "unknown"),
            "confirmation_id": data.get("confirmation_id"),
            "provider_request_id": data.get("provider_request_id"),
            "error": data.get("rejection_reason"),
        }
    except httpx.TimeoutException:
        # Submission reached the wire in the real world; treat as UNKNOWN.
        return {"status": "unknown", "message": "timeout after submission — reconcile by action_id"}
    except Exception as exc:  # noqa: BLE001 — activity reports, workflow decides
        logger.warning("submit_payment failed: %s", exc)
        raise


@activity.defn
async def check_payment_status(input_: Any) -> dict[str, Any]:
    """Poll the provider's status endpoint for a prior submission."""
    try:
        async with httpx.AsyncClient(timeout=_timeout()) as client:
            resp = await client.get(f"{_payment_provider_url()}/payments/status/{input_.action_id}")
            resp.raise_for_status()
            data = resp.json()
        return {
            "status": data.get("status", "unknown"),
            "confirmation_id": data.get("confirmation_id"),
            "provider_request_id": data.get("provider_request_id"),
            "error": data.get("rejection_reason"),
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("check_payment_status failed: %s", exc)
        return {"status": "unknown", "error": str(exc)}


# ── Audit recording (best-effort; DB sink lands in M6) ───────────────────────

@activity.defn
async def record_arrangement(result: PaymentArrangementResult) -> dict[str, Any]:
    """Append an immutable, append-only evidence line for the arrangement.

    Stand-in for the real audit sink; logs and appends to a JSONL file so
    outcomes are inspectable even without Postgres running.
    """
    data = {
        "arrangement_id": result.arrangement_id,
        "outcome": result.outcome,
        "confirmation_id": result.confirmation_id,
        "provider_request_id": result.provider_request_id,
        "reason": result.reason,
        "attempts": result.attempts,
        "recorded_at": datetime.utcnow().isoformat(),
    }
    logger.info("Arrangement recorded: %s", data)
    try:
        target = Path(__file__).parent.parent.parent / "data" / "arrangement_events.jsonl"
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(data) + "\n")
        return {"recorded": True, "path": str(target)}
    except Exception as exc:  # noqa: BLE001 — audit must never break the workflow
        logger.warning("record_arrangement failed (non-fatal): %s", exc)
        return {"recorded": False, "error": str(exc)}
