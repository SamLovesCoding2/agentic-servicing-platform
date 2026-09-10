"""
Mock Fictional Auto Credit (FAC) API.

Returns fake account data for auto-loan servicing.
All data is synthetic. No real customer information.
"""

from __future__ import annotations

import json
import os
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

app = FastAPI(title="Mock FAC API", version="0.1.0")

DATA_FILE = Path(__file__).parent / "data" / "accounts.json"


def _load_accounts() -> list[dict[str, Any]]:
    with open(DATA_FILE) as f:
        return json.load(f)


def _find_account(account_id: str) -> dict[str, Any] | None:
    for account in _load_accounts():
        if account["account_id"] == account_id:
            return account
    return None


def _json_safe(obj: Any) -> Any:
    """Convert Decimal/date to JSON-serializable types."""
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(item) for item in obj]
    return obj


# ── Models ──────────────────────────────────────────────────────────────────

class PaymentRequest(BaseModel):
    amount: str
    date: str
    method_token: str
    action_id: str  # idempotency key


class ServicingUpdateRequest(BaseModel):
    field: str  # "phone" | "address"
    value: dict[str, Any]


# ── Endpoints ───────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.get("/accounts/{account_id}/overview")
async def get_overview(account_id: str):
    account = _find_account(account_id)
    if not account:
        raise HTTPException(status_code=404, detail=f"Account {account_id} not found")
    return _json_safe(account["overview"])


@app.get("/accounts/{account_id}/servicing")
async def get_servicing(account_id: str):
    account = _find_account(account_id)
    if not account:
        raise HTTPException(status_code=404, detail=f"Account {account_id} not found")
    return _json_safe(account["servicing"])


@app.get("/accounts/{account_id}/payments")
async def get_payments(account_id: str):
    account = _find_account(account_id)
    if not account:
        raise HTTPException(status_code=404, detail=f"Account {account_id} not found")
    return _json_safe(account["payments"])


@app.get("/accounts/{account_id}/promises")
async def get_promises(account_id: str):
    account = _find_account(account_id)
    if not account:
        raise HTTPException(status_code=404, detail=f"Account {account_id} not found")
    return _json_safe(account["promises"])


@app.get("/accounts/{account_id}/negotiation_rules")
async def get_negotiation_rules(account_id: str):
    account = _find_account(account_id)
    if not account:
        raise HTTPException(status_code=404, detail=f"Account {account_id} not found")
    return _json_safe(account["negotiation_rules"])


@app.post("/accounts/{account_id}/payments")
async def schedule_payment(account_id: str, request: PaymentRequest):
    """
    Mock payment scheduling. Deterministic by action_id:
    same action_id always returns the same confirmation.
    """
    account = _find_account(account_id)
    if not account:
        raise HTTPException(status_code=404, detail=f"Account {account_id} not found")

    # Validate method token exists
    method_tokens = [m["method_token"] for m in account["payments"]["saved_methods"]]
    if request.method_token not in method_tokens:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid method token: {request.method_token}",
        )

    # Deterministic confirmation based on action_id hash
    confirmation_id = f"CONF-{abs(hash(request.action_id)) % 100000:05d}"

    return {
        "confirmation_id": confirmation_id,
        "account_id": account_id,
        "amount": request.amount,
        "date": request.date,
        "method_token": request.method_token,
        "action_id": request.action_id,
        "status": "confirmed",
        "timestamp": "2026-09-09T12:00:00Z",
    }


@app.post("/accounts/{account_id}/servicing")
async def update_servicing(account_id: str, request: ServicingUpdateRequest):
    account = _find_account(account_id)
    if not account:
        raise HTTPException(status_code=404, detail=f"Account {account_id} not found")

    if request.field not in ("phone", "address"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot update field: {request.field}",
        )

    return {
        "account_id": account_id,
        "updated_field": request.field,
        "new_value": request.value,
        "status": "updated",
        "timestamp": "2026-09-09T12:00:00Z",
    }


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("FAC_API_PORT", "9000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
