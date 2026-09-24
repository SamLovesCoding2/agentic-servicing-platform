"""Durable orchestration tests.

Two layers:
  1. Pure logic (always runs): outcomes / compliance mapping used by the
     workflow layer.
  2. Workflow execution (integration): runs the real workflows against the
     Temporal time-skipping test environment with *stubbed* activities, so
     nothing touches the network or a Temporal server. Skipped gracefully
     if the local dev-server binary cannot be provisioned.

Temporal resolves activities by name, so the test worker registers stub
functions with the same names (compliance_check, submit_payment,
check_payment_status, record_arrangement) to drive each scenario.
"""

from __future__ import annotations

import os

import pytest
from temporalio import activity

from taylor.orchestration.shared import (
    OUTCOME_CONFIRMED,
    OUTCOME_REJECTED,
    OUTCOME_UNKNOWN,
    PaymentArrangementInput,
    ReconcilePaymentInput,
)

# ── Scenarios for stub activities ────────────────────────────────────────────

SCENARIO = {"mode": "confirmed"}


@activity.defn(name="compliance_check")
async def _compliance_check_stub(input_):
    return {"decision": "allow", "blocked": False, "requires_step_up": False, "matched_rules": []}


@activity.defn(name="submit_payment")
async def _submit_payment_stub(input_):
    mode = SCENARIO["mode"]
    return {
        "status": mode,  # confirmed | rejected | unknown
        "confirmation_id": "CONF-STUB-001" if mode == "confirmed" else None,
        "provider_request_id": "PR-STUB-001",
        "error": None if mode != "rejected" else "insufficient funds",
    }


@activity.defn(name="check_payment_status")
async def _check_payment_status_stub(input_):
    mode = SCENARIO["mode"]
    counter = SCENARIO.setdefault("check_count", 0)
    if mode == "reconcile_then_confirmed":
        # One unknown poll, then confirmed.
        counter += 1
        SCENARIO["check_count"] = counter
        if counter == 1:
            return {"status": "unknown", "provider_request_id": "PR-STUB-001"}
        return {
            "status": "confirmed",
            "confirmation_id": "CONF-STUB-002",
            "provider_request_id": "PR-STUB-001",
        }
    if mode == "stays_unknown":
        return {"status": "unknown", "provider_request_id": "PR-STUB-001"}
    return {
        "status": mode,
        "confirmation_id": "CONF-STUB-001" if mode == "confirmed" else None,
        "provider_request_id": "PR-STUB-001",
        "error": None if mode != "rejected" else "insufficient funds",
    }


@activity.defn(name="record_arrangement")
async def _record_arrangement_stub(result):
    return {"recorded": True}


def _base_input(**overrides) -> PaymentArrangementInput:
    base = dict(
        arrangement_id="ARR-001",
        customer_id="cust_001",
        account_id="ACC-001",
        tenant="westpond",
        amount="300.00",
        scheduled_date="2026-10-05",
        method_token="pm_protected_demo",
        action_id="act-py-001",
        auth_level="step_up",
    )
    base.update(overrides)
    return PaymentArrangementInput(**base)


# ── Pure logic: outcome constants + compliance mapping ───────────────────────

def test_outcome_constants_are_stable_strings():
    assert OUTCOME_CONFIRMED == "confirmed"
    assert OUTCOME_REJECTED == "rejected"
    assert OUTCOME_UNKNOWN == "unknown"


@pytest.mark.asyncio
async def test_compliance_check_blocks_zero_amount_proposal():
    """The workflow's compliance gate must deny a $0.00 arrangement."""
    from taylor.orchestration.activities import compliance_check

    decision = await compliance_check(_base_input(amount="0.00"))
    assert decision["blocked"] is True
    codes = [m["reason_code"] for m in decision["matched_rules"]]
    assert "MIN_AMOUNT" in codes


@pytest.mark.asyncio
async def test_compliance_check_accepts_valid_proposal():
    from taylor.orchestration.activities import compliance_check

    decision = await compliance_check(_base_input(amount="300.00"))
    assert decision["blocked"] is False
    assert decision["requires_step_up"] is False


@pytest.mark.asyncio
async def test_compliance_check_rejects_non_step_up():
    from taylor.orchestration.activities import compliance_check

    decision = await compliance_check(_base_input(amount="300.00", auth_level="verified"))
    assert decision["requires_step_up"] is True


# ── Workflow execution (integration; skips if the dev server is unavailable) ──

@pytest.mark.asyncio
async def _run_arrangement(mode: str):
    from temporalio.testing import WorkflowEnvironment
    from temporalio.worker import Worker

    from taylor.orchestration.workflows import PaymentArrangementWorkflow

    SCENARIO.update({"mode": mode, "check_count": 0})

    env = await WorkflowEnvironment.start_time_skipping()
    try:
        async with env:
            worker = Worker(
                env.client,
                task_queue="test-queue",
                workflows=[PaymentArrangementWorkflow],
                activities=[
                    _compliance_check_stub,
                    _submit_payment_stub,
                    _check_payment_status_stub,
                    _record_arrangement_stub,
                ],
            )
            async with worker:
                handle = await env.client.start_workflow(
                    "PaymentArrangementWorkflow",
                    _base_input(),
                    id=f"test-arr-{mode}",
                    task_queue="test-queue",
                )
                raw = await handle.result()
                from taylor.orchestration.shared import PaymentArrangementResult
                return PaymentArrangementResult(**raw)
    finally:
        await env.shutdown()


@pytest.mark.skipif(
    os.environ.get("TEMPORAL_INTEGRATION", "0") not in ("1", "true"),
    reason="set TEMPORAL_INTEGRATION=1 to run Temporal workflow tests (provisions the dev server binary)",
)
@pytest.mark.asyncio
async def test_arrangement_confirmed_directly():
    result = await _run_arrangement("confirmed")
    assert result.outcome == OUTCOME_CONFIRMED
    assert result.confirmation_id == "CONF-STUB-001"
    assert result.attempts == 0


@pytest.mark.skipif(
    os.environ.get("TEMPORAL_INTEGRATION", "0") not in ("1", "true"),
    reason="set TEMPORAL_INTEGRATION=1 to run Temporal workflow tests",
)
@pytest.mark.asyncio
async def test_arrangement_rejected_by_provider():
    result = await _run_arrangement("rejected")
    assert result.outcome == OUTCOME_REJECTED
    assert result.reason == "insufficient funds"


@pytest.mark.skipif(
    os.environ.get("TEMPORAL_INTEGRATION", "0") not in ("1", "true"),
    reason="set TEMPORAL_INTEGRATION=1 to run Temporal workflow tests",
)
@pytest.mark.asyncio
async def test_arrangement_reconciles_unknown_to_confirmed():
    result = await _run_arrangement("reconcile_then_confirmed")
    assert result.outcome == OUTCOME_CONFIRMED
    assert result.confirmation_id == "CONF-STUB-002"
    assert result.attempts >= 1


@pytest.mark.skipif(
    os.environ.get("TEMPORAL_INTEGRATION", "0") not in ("1", "true"),
    reason="set TEMPORAL_INTEGRATION=1 to run Temporal workflow tests",
)
@pytest.mark.asyncio
async def test_arrangement_unknown_when_reconciliation_exhausted():
    result = await _run_arrangement("stays_unknown")
    assert result.outcome == OUTCOME_UNKNOWN
    assert result.attempts == 5


@pytest.mark.skipif(
    os.environ.get("TEMPORAL_INTEGRATION", "0") not in ("1", "true"),
    reason="set TEMPORAL_INTEGRATION=1 to run Temporal workflow tests",
)
@pytest.mark.asyncio
async def test_reconcile_workflow_recovers_unknown():
    from temporalio.testing import WorkflowEnvironment
    from temporalio.worker import Worker

    from taylor.orchestration.workflows import ReconcilePaymentWorkflow

    SCENARIO.update({"mode": "reconcile_then_confirmed", "check_count": 0})
    env = await WorkflowEnvironment.start_time_skipping()
    try:
        async with env:
            worker = Worker(
                env.client,
                task_queue="test-queue",
                workflows=[ReconcilePaymentWorkflow],
                activities=[_check_payment_status_stub, _record_arrangement_stub],
            )
            async with worker:
                handle = await env.client.start_workflow(
                    "ReconcilePaymentWorkflow",
                    ReconcilePaymentInput(
                        action_id="act-unknown-001",
                        account_id="ACC-001",
                        max_attempts=5,
                    ),
                    id="test-reconcile-001",
                    task_queue="test-queue",
                )
                raw = await handle.result()
                from taylor.orchestration.shared import ReconcilePaymentResult
                result = ReconcilePaymentResult(**raw)
    finally:
        await env.shutdown()

    assert result.outcome == OUTCOME_CONFIRMED
    assert result.attempts == 2
