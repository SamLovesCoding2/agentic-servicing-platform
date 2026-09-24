"""Temporal workflow definitions — deterministic coordination only.

Rules for workflow code:
  - No I/O, no randomness, no wall-clock time. All side effects live in
    activities.py; time comes from ``workflow.now()``.

  - ``PaymentArrangementWorkflow``: compliance gate → durable wait until
    the scheduled date → submit payment → durable reconciliation of any
    UNKNOWN outcome. Survives worker restarts across the whole period.

  - ``ReconcilePaymentWorkflow``: standalone recovery worker for actions
    stuck in UNKNOWN (e.g. a timeout that never resolved).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from taylor.orchestration.shared import (
    OUTCOME_CONFIRMED,
    OUTCOME_REJECTED,
    OUTCOME_UNKNOWN,
    PaymentArrangementInput,
    PaymentArrangementResult,
    ReconcilePaymentInput,
    ReconcilePaymentResult,
)

with workflow.unsafe.imports_passed_through():
    # Activities live in-process as worker-registered functions; the pass-
    # through block keeps Temporal's sandbox from intercepting the activity
    # module (which imports httpx).
    from taylor.orchestration.activities import (
        check_payment_status,
        compliance_check,
        record_arrangement,
        submit_payment,
    )

_ACTIVITY_TIMEOUT = timedelta(seconds=30)


@workflow.defn
class PaymentArrangementWorkflow:
    """Create a future-dated payment arrangement and see it through."""

    @workflow.run
    async def run(self, inp: PaymentArrangementInput) -> PaymentArrangementResult:
        # 1. Compliance gate — fail-closed, before any money movement.
        policy = await workflow.execute_activity(
            compliance_check,
            inp,
            schedule_to_close_timeout=_ACTIVITY_TIMEOUT,
        )
        if policy.get("blocked"):
            reasons = ", ".join(
                m["reason_code"]
                for m in policy.get("matched_rules", [])
                if m.get("decision") in ("deny", "require_agent")
            )
            result = PaymentArrangementResult(
                arrangement_id=inp.arrangement_id,
                outcome=OUTCOME_REJECTED,
                reason=f"compliance policy blocked: {reasons}",
            )
            await self._record(result)
            return result
        if policy.get("requires_step_up"):
            result = PaymentArrangementResult(
                arrangement_id=inp.arrangement_id,
                outcome=OUTCOME_REJECTED,
                reason="compliance policy requires step-up authentication",
            )
            await self._record(result)
            return result

        # 2. Durable wait until the scheduled date (survives restarts).
        try:
            # Temporal's workflow clock is UTC-aware; make the target the same.
            target = datetime.fromisoformat(f"{inp.scheduled_date}T00:00:00").replace(
                tzinfo=UTC
            )
        except ValueError:
            result = PaymentArrangementResult(
                arrangement_id=inp.arrangement_id,
                outcome=OUTCOME_REJECTED,
                reason=f"invalid scheduled_date: {inp.scheduled_date!r}",
            )
            await self._record(result)
            return result

        now = workflow.now()
        if target > now:
            await workflow.sleep(target - now)

        # 3. Submit (idempotent by action_id; HTTP failures retry, business
        #    outcomes pass through as status).
        submission = await workflow.execute_activity(
            submit_payment,
            inp,
            schedule_to_close_timeout=_ACTIVITY_TIMEOUT + timedelta(seconds=10),
            retry_policy=RetryPolicy(
                maximum_attempts=3,
                initial_interval=timedelta(seconds=2),
                backoff_coefficient=2.0,
            ),
        )

        status = submission.get("status")
        if status == "confirmed":
            result = PaymentArrangementResult(
                arrangement_id=inp.arrangement_id,
                outcome=OUTCOME_CONFIRMED,
                confirmation_id=submission.get("confirmation_id"),
                provider_request_id=submission.get("provider_request_id"),
            )
            await self._record(result)
            return result
        if status == "rejected":
            result = PaymentArrangementResult(
                arrangement_id=inp.arrangement_id,
                outcome=OUTCOME_REJECTED,
                reason=submission.get("error"),
                provider_request_id=submission.get("provider_request_id"),
            )
            await self._record(result)
            return result

        # 4. Reconcile UNKNOWN with durable backoff, then give up as UNKNOWN.
        attempts = 0
        max_attempts = 5
        backoff = (5, 10, 20, 40)
        while attempts < max_attempts:
            await workflow.sleep(timedelta(seconds=backoff[attempts % len(backoff)]))
            attempts += 1
            status_resp = await workflow.execute_activity(
                check_payment_status,
                ReconcilePaymentInput(
                    action_id=inp.action_id,
                    account_id=inp.account_id,
                    amount=inp.amount,
                    scheduled_date=inp.scheduled_date,
                    tenant=inp.tenant,
                    auth_level=inp.auth_level,
                ),
                schedule_to_close_timeout=_ACTIVITY_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            s = status_resp.get("status")
            if s == "confirmed":
                result = PaymentArrangementResult(
                    arrangement_id=inp.arrangement_id,
                    outcome=OUTCOME_CONFIRMED,
                    confirmation_id=status_resp.get("confirmation_id"),
                    provider_request_id=status_resp.get("provider_request_id"),
                    attempts=attempts,
                )
                await self._record(result)
                return result
            if s == "rejected":
                result = PaymentArrangementResult(
                    arrangement_id=inp.arrangement_id,
                    outcome=OUTCOME_REJECTED,
                    reason=status_resp.get("error"),
                    provider_request_id=status_resp.get("provider_request_id"),
                    attempts=attempts,
                )
                await self._record(result)
                return result
            # still unknown — loop with backoff

        result = PaymentArrangementResult(
            arrangement_id=inp.arrangement_id,
            outcome=OUTCOME_UNKNOWN,
            reason="reconciliation exhausted without a terminal provider status",
            attempts=attempts,
        )
        await self._record(result)
        return result

    async def _record(self, result: PaymentArrangementResult) -> None:
        """Best-effort durable audit. Never fails the workflow."""
        try:
            await workflow.execute_activity(
                record_arrangement,
                result,
                schedule_to_close_timeout=timedelta(seconds=15),
            )
        except Exception:  # noqa: BLE001
            workflow.logger.warning("record_arrangement failed (non-fatal)")


@workflow.defn
class ReconcilePaymentWorkflow:
    """Recover a single UNKNOWN action to a terminal state."""

    @workflow.run
    async def run(self, inp: ReconcilePaymentInput) -> ReconcilePaymentResult:
        attempts = 0
        while attempts < inp.max_attempts:
            await workflow.sleep(
                timedelta(seconds=inp.backoff_seconds[attempts % len(inp.backoff_seconds)])
            )
            attempts += 1
            resp = await workflow.execute_activity(
                check_payment_status,
                inp,
                schedule_to_close_timeout=_ACTIVITY_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            status = resp.get("status")
            if status in ("confirmed", "rejected"):
                return ReconcilePaymentResult(
                    action_id=inp.action_id,
                    outcome=status,
                    confirmation_id=resp.get("confirmation_id"),
                    provider_request_id=resp.get("provider_request_id"),
                    attempts=attempts,
                )
        return ReconcilePaymentResult(
            action_id=inp.action_id,
            outcome=OUTCOME_UNKNOWN,
            attempts=attempts,
        )
