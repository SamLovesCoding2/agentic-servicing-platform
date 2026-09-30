"""Structured, privacy-aware turn traces.

The graph state contains protected values that must never enter prompts,
analytics, or traces. This module provides a small vendor-neutral sink
contract and uses the OpenTelemetry API as an optional no-op span backend.
Set ``TRACE_JSONL_PATH`` to persist one redacted record per line locally.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from opentelemetry import trace
from opentelemetry.trace import Span, Status, StatusCode

_TRACER = trace.get_tracer("agentic_servicing_platform.agent")
_REDACTED = "[REDACTED]"
_MAX_STRING_LENGTH = 1_000
_SENSITIVE_KEYS = {
    "api_key",
    "authorization",
    "authorization_artifact",
    "credential_token",
    "method_token",
    "password",
    "secret",
    "token",
}


def redact(value: Any, *, key: str | None = None) -> Any:
    """Return a JSON-safe value with protected-looking fields redacted."""
    normalized_key = key.lower() if key else ""
    if (
        normalized_key in _SENSITIVE_KEYS
        or normalized_key.endswith("_token")
        or normalized_key.endswith("_secret")
    ):
        return _REDACTED
    if isinstance(value, dict):
        return {str(k): redact(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [redact(item) for item in value]
    if isinstance(value, Enum):
        return redact(value.value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, str):
        return value[:_MAX_STRING_LENGTH]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:_MAX_STRING_LENGTH]


def utterance_fingerprint(utterance: str) -> str:
    """Create a non-reversible identifier for correlating repeated inputs."""
    return hashlib.sha256(utterance.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class TraceRecord:
    """A single event in a turn trace."""

    timestamp: str
    event: str
    conversation_id: str
    turn_id: str
    fields: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "event": self.event,
            "conversation_id": self.conversation_id,
            "turn_id": self.turn_id,
            "fields": self.fields,
        }


class TraceSink(Protocol):
    """Destination for already-redacted trace records."""

    def write(self, record: TraceRecord) -> None:
        """Persist or observe one trace record."""


class NullTraceSink:
    """Default sink when no local trace output is configured."""

    def write(self, record: TraceRecord) -> None:
        del record


class InMemoryTraceSink:
    """Deterministic sink for tests and local demonstrations."""

    def __init__(self) -> None:
        self._records: list[TraceRecord] = []

    @property
    def records(self) -> list[TraceRecord]:
        return list(self._records)

    def write(self, record: TraceRecord) -> None:
        self._records.append(record)


class JsonlTraceSink:
    """Append-only JSONL sink suitable for local development."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def write(self, record: TraceRecord) -> None:
        line = json.dumps(record.as_dict(), sort_keys=True, default=str)
        with self._lock, self._path.open("a", encoding="utf-8") as output:
            output.write(line + "\n")


def build_trace_sink() -> TraceSink:
    """Build the configured local sink without requiring a telemetry vendor."""
    path = os.environ.get("TRACE_JSONL_PATH")
    return JsonlTraceSink(path) if path else NullTraceSink()


def _span_attributes(fields: dict[str, Any]) -> dict[str, str | int | float | bool]:
    """Flatten safe fields into OpenTelemetry-compatible primitive attributes."""
    result: dict[str, str | int | float | bool] = {}
    for key, value in fields.items():
        safe_value = redact(value, key=key)
        if isinstance(safe_value, (str, int, float, bool)):
            result[key] = safe_value
        else:
            result[key] = json.dumps(safe_value, sort_keys=True, default=str)
    return result


class TurnTrace:
    """Records lifecycle events for one turn and closes an OpenTelemetry span."""

    def __init__(
        self,
        conversation_id: str,
        turn_id: str,
        sink: TraceSink | None = None,
    ) -> None:
        self._conversation_id = conversation_id
        self._turn_id = turn_id
        self._sink = sink or NullTraceSink()
        self._started = time.monotonic()
        self._span: Span = _TRACER.start_span("agent.turn")
        self._span.set_attribute("conversation_id", conversation_id)
        self._span.set_attribute("turn_id", turn_id)

    def event(self, name: str, **fields: Any) -> None:
        safe_fields = redact(fields)
        record = TraceRecord(
            timestamp=datetime.now().astimezone().isoformat(),
            event=name,
            conversation_id=self._conversation_id,
            turn_id=self._turn_id,
            fields=safe_fields,
        )
        self._sink.write(record)
        self._span.add_event(name, _span_attributes(safe_fields))

    def finish(self, status: str = "completed", **fields: Any) -> None:
        duration_ms = round((time.monotonic() - self._started) * 1_000, 2)
        self.event("turn.finished", status=status, duration_ms=duration_ms, **fields)
        self._span.set_attribute("turn.status", status)
        self._span.set_attribute("turn.duration_ms", duration_ms)
        self._span.set_status(Status(StatusCode.OK if status == "completed" else StatusCode.ERROR))
        self._span.end()

    def fail(self, error_type: str) -> None:
        self.finish(status="failed", error_type=error_type)
