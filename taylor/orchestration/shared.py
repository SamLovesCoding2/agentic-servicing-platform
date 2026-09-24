"""Types shared between workflows and activities.

Kept data-only (plain dataclasses + string outcomes) so both the workflow
and activity process can import them without touching non-deterministic
code or the Temporal runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Outcome values (plain strings; Temporal converters handle these trivially).
OUTCOME_REJECTED = "rejected"
OUTCOME_CONFIRMED = "confirmed"
OUTCOME_UNKNOWN = "unknown"
OUTCOME_CANCELLED = "cancelled"


@dataclass
class PaymentArrangementInput:
    """What the platform asks the workflow to do."""

    arrangement_id: str
    customer_id: str
    account_id: str
    tenant: str = "westpond"
    amount: str = "0.00"                 # decimal string
    scheduled_date: str = "2026-12-31"   # ISO date (YYYY-MM-DD)
    method_token: str = ""               # opaque token, never PAN
    action_id: str = ""                  # idempotency key
    auth_level: str = "step_up"
    disclosures: tuple[str, ...] = field(default_factory=tuple)


@dataclass
class PaymentArrangementResult:
    arrangement_id: str
    outcome: str
    confirmation_id: str | None = None
    provider_request_id: str | None = None
    reason: str | None = None
    attempts: int = 0


@dataclass
class ReconcilePaymentInput:
    """A payment stuck in UNKNOWN that needs reconciliation."""

    action_id: str
    account_id: str
    amount: str = "0.00"
    scheduled_date: str = "2026-12-31"
    tenant: str = "westpond"
    auth_level: str = "step_up"
    max_attempts: int = 5
    backoff_seconds: tuple[int, ...] = (5, 10, 20, 40)


@dataclass
class ReconcilePaymentResult:
    action_id: str
    outcome: str
    confirmation_id: str | None = None
    provider_request_id: str | None = None
    attempts: int = 0
