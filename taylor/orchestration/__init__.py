"""Durable orchestration (M2) — Temporal workflows for multi-day arrangements.

Coordination code lives in ``workflows.py`` (deterministic, no I/O). All
side effects live in ``activities.py``. Workflow results use plain strings
for outcome to keep the Temporal converter simple.

Design notes:
  - ``PaymentArrangementWorkflow`` validates the request against the
    compliance engine, waits durably until the scheduled date, submits the
    payment, then reconciles UNKNOWN outcomes with durable backoff.
  - ``ReconcilePaymentWorkflow`` is the standalone reconciliation worker
    for actions already stuck in UNKNOWN.
  - Every wait is a durable Temporal timer: the workflow survives worker
    restarts and deploys.
"""
