"""Temporal worker entrypoint.

Runs the durable orchestration worker against a Temporal server.

    python -m taylor.orchestration.worker                # localhost:7233
    TEMPORAL_ADDRESS=localhost:7233 TEMPORAL_TASK_QUEUE=agentic-taylor \
        python -m taylor.orchestration.worker

Start a server first with the m2 compose profile:

    docker compose --profile m2 up -d temporal
"""

from __future__ import annotations

import asyncio
import os

from temporalio.client import Client
from temporalio.worker import Worker

from taylor.orchestration.activities import (
    check_payment_status,
    compliance_check,
    record_arrangement,
    submit_payment,
)
from taylor.orchestration.workflows import (
    PaymentArrangementWorkflow,
    ReconcilePaymentWorkflow,
)


async def main() -> None:
    address = os.environ.get("TEMPORAL_ADDRESS", "localhost:7233")
    namespace = os.environ.get("TEMPORAL_NAMESPACE", "default")
    task_queue = os.environ.get("TEMPORAL_TASK_QUEUE", "agentic-taylor")

    client = await Client.connect(address, namespace=namespace)
    worker = Worker(
        client,
        task_queue=task_queue,
        workflows=[PaymentArrangementWorkflow, ReconcilePaymentWorkflow],
        activities=[
            compliance_check,
            submit_payment,
            check_payment_status,
            record_arrangement,
        ],
    )
    print(f"Temporal worker connected to {address} (ns={namespace}, queue={task_queue})")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
