from pathlib import Path

from taylor.observability.tracing import (
    InMemoryTraceSink,
    JsonlTraceSink,
    TurnTrace,
    redact,
)
from taylor.runtime.text_runtime import TextRuntime


def test_redact_removes_protected_values_recursively():
    value = {
        "credential_token": "tok-secret",
        "nested": {"method_token": "method-secret"},
        "safe": "visible",
    }

    redacted = redact(value)

    assert redacted == {
        "credential_token": "[REDACTED]",
        "nested": {"method_token": "[REDACTED]"},
        "safe": "visible",
    }


def test_turn_trace_records_lifecycle_without_raw_utterance():
    sink = InMemoryTraceSink()
    trace = TurnTrace("conversation-1", "turn-1", sink=sink)

    trace.event("turn.started", utterance_sha256="hashed", credential_token="secret")
    trace.finish(route="knowledge")

    assert [record.event for record in sink.records] == [
        "turn.started",
        "turn.finished",
    ]
    assert sink.records[0].fields["credential_token"] == "[REDACTED]"
    assert "secret" not in str(sink.records)
    assert "hashed" in str(sink.records)


def test_jsonl_trace_sink_writes_one_json_record(tmp_path: Path):
    path = tmp_path / "traces" / "turns.jsonl"
    sink = JsonlTraceSink(path)
    trace = TurnTrace("conversation-1", "turn-1", sink=sink)

    trace.finish(status="completed")

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert '"event": "turn.finished"' in lines[0]


async def test_text_runtime_emits_trace_events():
    sink = InMemoryTraceSink()
    runtime = TextRuntime(force_deterministic=True, trace_sink=sink)

    await runtime.run_turn(
        utterance="What happens if I miss a payment?",
        conversation_id="trace-conversation",
        customer_id="customer-1",
        auth_level="anonymous",
        channel="chat",
    )

    assert [record.event for record in sink.records] == [
        "turn.started",
        "turn.routed",
        "turn.reasoned",
        "turn.gate_checked",
        "turn.finished",
    ]
    assert all("What happens" not in str(record.fields) for record in sink.records)
