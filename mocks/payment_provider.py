"""
Mock Payment Provider.

Simulates a payment processor with deterministic behavior based on action_id.
Supports idempotency: same action_id always returns the same result.
Can simulate timeouts and failures for testing UNKNOWN state handling.
"""

from __future__ import annotations

import hashlib
import os
import time
from typing import Any

from fastapi import FastAPI, Query
from pydantic import BaseModel

app = FastAPI(title="Mock Payment Provider", version="0.1.0")

# In-memory store for idempotency: action_id → response
_idempotency_store: dict[str, dict[str, Any]] = {}


class PaymentSubmission(BaseModel):
    action_id: str
    account_id: str
    amount: str
    date: str
    method_token: str


def _deterministic_outcome(action_id: str) -> str:
    """Deterministic outcome based on action_id hash."""
    h = int(hashlib.sha256(action_id.encode()).hexdigest(), 16)
    # 90% confirmed, 5% rejected, 5% unknown (timeout)
    remainder = h % 100
    if remainder < 90:
        return "confirmed"
    elif remainder < 95:
        return "rejected"
    else:
        return "unknown"


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.post("/payments/submit")
async def submit_payment(
    submission: PaymentSubmission,
    simulate_timeout: bool = Query(False, description="Force a timeout response"),
):
    """Submit a payment. Returns confirmed, rejected, or times out."""
    # Check idempotency store first
    if submission.action_id in _idempotency_store:
        return _idempotency_store[submission.action_id]

    if simulate_timeout:
        # Simulate a timeout — no response stored, caller gets nothing
        # In real life this would be a network timeout
        time.sleep(30)
        return {"error": "timeout"}

    outcome = _deterministic_outcome(submission.action_id)

    if outcome == "unknown":
        # Simulate timeout: don't store a response
        # The caller will time out, and the reconciliation endpoint will return "unknown"
        return {"error": "timeout_simulated"}

    response: dict[str, Any] = {
        "action_id": submission.action_id,
        "provider_request_id": f"PR-{hashlib.sha256(submission.action_id.encode()).hexdigest()[:12]}",
        "status": outcome,
        "amount": submission.amount,
        "date": submission.date,
        "confirmation_id": f"CONF-{hashlib.sha256(submission.action_id.encode()).hexdigest()[:8]}" if outcome == "confirmed" else None,
        "rejection_reason": "Insufficient funds" if outcome == "rejected" else None,
        "timestamp": "2026-09-09T12:00:00Z",
    }

    _idempotency_store[submission.action_id] = response
    return response


@app.get("/payments/status/{action_id}")
async def get_payment_status(action_id: str):
    """Reconciliation endpoint: check status of a payment by action_id."""
    if action_id in _idempotency_store:
        return _idempotency_store[action_id]

    # Not in store — either timed out or still processing
    # For the mock, we resolve it deterministically
    outcome = _deterministic_outcome(action_id)
    if outcome == "unknown":
        # Still unknown after reconciliation
        return {
            "action_id": action_id,
            "status": "unknown",
            "message": "Provider status not yet available",
        }

    response: dict[str, Any] = {
        "action_id": action_id,
        "provider_request_id": f"PR-{hashlib.sha256(action_id.encode()).hexdigest()[:12]}",
        "status": outcome,
        "confirmation_id": f"CONF-{hashlib.sha256(action_id.encode()).hexdigest()[:8]}" if outcome == "confirmed" else None,
        "rejection_reason": "Insufficient funds" if outcome == "rejected" else None,
        "timestamp": "2026-09-09T12:00:00Z",
    }

    _idempotency_store[action_id] = response
    return response


@app.delete("/payments/_reset")
async def reset_store():
    """Clear idempotency store (for testing)."""
    global _idempotency_store
    _idempotency_store = {}
    return {"status": "reset"}


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PAYMENT_PROVIDER_PORT", "9001"))
    uvicorn.run(app, host="0.0.0.0", port=port)
