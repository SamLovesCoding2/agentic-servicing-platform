"""Temporal client helpers + CLI.

Start an arrangement workflow and fetch its result:

    python -m taylor.orchestration.client schedule \
        --arrangement-id ARR-001 --account-id ACC-001 \
        --amount 300.00 --date 2026-10-05 --action-id py-test-001

    python -m taylor.orchestration.client result <workflow_id>
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from temporalio.client import Client

from taylor.orchestration.shared import (
    PaymentArrangementInput,
    ReconcilePaymentInput,
)

_DEFAULT_TASK_QUEUE = "agentic-taylor"


async def connect() -> tuple[Client, str]:
    address = os.environ.get("TEMPORAL_ADDRESS", "localhost:7233")
    namespace = os.environ.get("TEMPORAL_NAMESPACE", "default")
    client = await Client.connect(address, namespace=namespace)
    return client, os.environ.get("TEMPORAL_TASK_QUEUE", _DEFAULT_TASK_QUEUE)


async def start_arrangement(inp: PaymentArrangementInput) -> str:
    """Start a PaymentArrangementWorkflow; returns the workflow id."""
    client, task_queue = await connect()
    handle = await client.start_workflow(
        "PaymentArrangementWorkflow",
        inp,
        id=f"arrangement-{inp.arrangement_id}",
        task_queue=task_queue,
    )
    return handle.id


async def start_reconciliation(inp: ReconcilePaymentInput) -> str:
    client, task_queue = await connect()
    handle = await client.start_workflow(
        "ReconcilePaymentWorkflow",
        inp,
        id=f"reconcile-{inp.action_id}",
        task_queue=task_queue,
    )
    return handle.id


async def get_result(workflow_id: str) -> dict:
    client, _ = await connect()
    handle = client.get_workflow_handle(workflow_id)
    return await handle.result()  # waits for terminal state


def _parse_schedule_args(argv: list[str]) -> PaymentArrangementInput:
    p = argparse.ArgumentParser(prog="schedule")
    p.add_argument("--arrangement-id", required=True)
    p.add_argument("--account-id", required=True)
    p.add_argument("--customer-id", default="cust_demo_001")
    p.add_argument("--amount", default="300.00")
    p.add_argument("--date", required=True, help="ISO date YYYY-MM-DD")
    p.add_argument("--action-id", required=True, help="idempotency key")
    p.add_argument("--method-token", default="pm_protected_demo")
    p.add_argument("--tenant", default="westpond")
    p.add_argument("--auth-level", default="step_up")
    args = p.parse_args(argv)
    return PaymentArrangementInput(
        arrangement_id=args.arrangement_id,
        customer_id=args.customer_id,
        account_id=args.account_id,
        tenant=args.tenant,
        amount=args.amount,
        scheduled_date=args.date,
        method_token=args.method_token,
        action_id=args.action_id,
        auth_level=args.auth_level,
    )


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    if not args or args[0] not in ("schedule", "reconcile", "result"):
        print(__doc__)
        raise SystemExit(2)

    cmd = args[0]
    rest = args[1:]
    if cmd == "schedule":
        inp = _parse_schedule_args(rest)
        wid = asyncio.run(start_arrangement(inp))
        print(f"Started arrangement workflow: {wid}")
    elif cmd == "reconcile":
        p = argparse.ArgumentParser(prog="reconcile")
        p.add_argument("--action-id", required=True)
        p.add_argument("--account-id", default="ACC-001")
        p.add_argument("--amount", default="300.00")
        p.add_argument("--date", default="2026-12-31")
        p.add_argument("--max-attempts", type=int, default=5)
        a = p.parse_args(rest)
        wid = asyncio.run(
            start_reconciliation(
                ReconcilePaymentInput(
                    action_id=a.action_id,
                    account_id=a.account_id,
                    amount=a.amount,
                    scheduled_date=a.date,
                    max_attempts=a.max_attempts,
                )
            )
        )
        print(f"Started reconciliation workflow: {wid}")
    else:
        if not rest:
            print("usage: client result <workflow_id>")
            raise SystemExit(2)
        result = asyncio.run(get_result(rest[0]))
        print(result)


if __name__ == "__main__":
    main()
