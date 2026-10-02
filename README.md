# Agentic Servicing Platform

A production-style conversational AI platform for regulated customer interactions. Built with deterministic safety boundaries around nondeterministic LLM reasoning.

[![CI — Backend](https://github.com/SamLovesCoding2/agentic-servicing-platform/actions/workflows/ci.yml/badge.svg?job=backend)](https://github.com/SamLovesCoding2/agentic-servicing-platform/actions/workflows/ci.yml)
[![CI — Frontend](https://github.com/SamLovesCoding2/agentic-servicing-platform/actions/workflows/ci.yml/badge.svg?job=frontend)](https://github.com/SamLovesCoding2/agentic-servicing-platform/actions/workflows/ci.yml)

## Documentation

- [Technical Architecture](docs/technical-architecture.md) — 21-section deep dive: topology, auth, tool envelope, state machine, compliance, observability
- [Local Running Guide & Limitations](docs/local-limitations.md) — run everything locally for free; what costs money and what doesn't

## Architecture

The system separates nondeterministic reasoning (LLM) from deterministic boundaries (code). The model interprets language and proposes actions. Code decides whether actions are allowed, validates inputs, executes exactly once, records evidence, and decides what the customer may safely be told.

```
customer input
     │
     ▼
channel ingress ──► identity/session boundary ──► turn coordinator
                                                    │
                              ┌─────────────────────┼─────────────────────┐
                              ▼                     ▼                     ▼
                       specialist graph       policy engine        context reader
                              │                     │                     │
                              └──────────────┬──────┴─────────────────────┘
                                             ▼
                                     validated action plan
                                             │
                              ┌──────────────┴──────────────┐
                              ▼                             ▼
                       sensitive-action gate          ordinary tool
                              │                             │
                              └──────────────┬──────────────┘
                                             ▼
                                      execution evidence
                                             │
                           persist state ─► render reply ─► channel egress
```

### Core Components

| Component | Role |
|---|---|
| **Taylor** (agent core) | LangGraph-based graph with capability-scoped subgraphs |
| **Marshall** (backend) | FastAPI with channel adapters, turn coordinator, tool registry |
| **Tool Registry** | Capability-based tool exposure with read/proposal/execution classification |
| **State Machine** | PROPOSED → NORMALIZED → VALIDATED → AUTHORIZED → EXECUTING → CONFIRMED / UNKNOWN |
| **Compliance Engine** | Stateless, strictest-wins, fail-closed (M2+) |
| **Temporal** | Durable orchestration for multi-day workflows (M2+) |

### Graph Topology

```
START → preconditions → router → [knowledge | account_servicing | arrangement | sensitive_action | compliance_handoff] → completion_gate → END
```

Each subgraph has:
- A declared contract (allowed inputs, writable state, tool authority, required exits)
- Private state for internal reasoning
- A bounded tool allowlist enforced in the registry, not the prompt
- Validated exit states enforced by the completion gate

### Key Design Principles

1. **Model proposes, code executes.** The model can only move a request to `PROPOSED`. Deterministic code controls normalization, validation, authorization, execution, and confirmation.
2. **Capability-based tool exposure.** Execution tools are hidden from the model until preconditions are met. This is enforced in the registry, not the prompt.
3. **UNKNOWN is not failure.** A timeout after submission requires reconciliation by idempotency key. The agent says "pending," not "failed" or "succeeded."
4. **Persist before success language.** Success language is only permitted after `CONFIRMED` is in the database. The completion gate enforces this.
5. **Versioned authorization.** Authorization binds actor + amount + date + method + disclosures. If any field changes, consent is invalid.
6. **Server-derived identity.** The model cannot supply customer IDs, auth levels, or account references. These come from the authenticated session.
7. **Transcript is evidence, not source of truth.** Business state lives in normalized DB fields with versioning and provenance.

## Setup

### Prerequisites

- Python 3.11+
- Docker and Docker Compose

### Installation

```bash
# Clone the repo
git clone <your-repo-url> agentic-servicing-platform
cd agentic-servicing-platform

# Create virtual environment
python3.11 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e ".[dev]"

# Copy environment file
cp .env.example .env
# Edit .env and add your OpenAI API key
```

### Running Infrastructure

```bash
# Start PostgreSQL, Redis, mock FAC API, mock payment provider, Jaeger
docker compose up -d postgres redis mock-fac mock-payment jaeger

# Verify services are healthy
docker compose ps
```

### Running Tests

```bash
# Run the full test suite
pytest

# Run with coverage
pytest --cov=taylor --cov=marshall

# Run specific test category
pytest taylor/tests/test_router.py -v
pytest taylor/tests/test_state.py -v
pytest taylor/tests/test_registry.py -v
```

### Running Evaluations

The deterministic evaluation runner checks routing, channel safety, authorization,
compliance preemption, completion gates, and output filtering. It emits a JSON report
that can be used as a CI quality gate:

```bash
python -m evals.runner --cases evals/cases.json --fail-under 1.0
python -m evals.runner --cases evals/cases.json --json-out eval-report.json
```

Evaluation traces can be written locally as privacy-filtered JSONL:

```bash
TRACE_JSONL_PATH=./var/traces.jsonl \
  MARSHALL_LLM_ENABLED=0 \
  uvicorn marshall.app.main:app --port 8000
```

Traces contain correlation IDs, route, gate, tool-count, timing, and model-usage
metadata. Raw utterances and protected tokens are not written to the trace sink.

### Running the Mock Services Standalone

```bash
# Mock FAC API (port 9000)
python -m mocks.fac_api.app

# Mock Payment Provider (port 9001)
python -m mocks.payment_provider
```

### Running the Web Chat Channel (M4)

```bash
# Deterministic mode (no LLM credits consumed)
MARSHALL_LLM_ENABLED=0 uvicorn marshall.app.main:app --port 8000

# With LLM (requires OPENAI_API_KEY in .env; auto-detected)
uvicorn marshall.app.main:app --port 8000
```

Then open <http://localhost:8000/chat> for the demo widget, or use the API:

```bash
curl -X POST http://localhost:8000/api/chat/sessions \
  -H "Content-Type: application/json" -d '{"customer_id":"cust_demo_001"}'

curl -X POST http://localhost:8000/api/chat/sessions/<session_id>/messages \
  -H "Content-Type: application/json" -d '{"message":"What is my balance?"}'
```

Chat is architecturally barred from payment execution: the router blocks
`sensitive_action` on the chat channel and the channel tool override omits
`schedule_payment`.

### Running the Voice Channel (M5)

The voice channel keeps Taylor as the agent and uses ElevenLabs at the media
boundary. Transcript-only turns are free and deterministic. Audio transcription
and speech synthesis require an ElevenLabs API key and voice ID.

```bash
# Optional .env values:
ELEVENLABS_API_KEY=your-key
ELEVENLABS_VOICE_ID=your-voice-id

MARSHALL_LLM_ENABLED=0 uvicorn marshall.app.main:app --port 8000
```

Create a voice session and run a transcript-only turn:

```bash
curl -X POST http://localhost:8000/api/voice/sessions \
  -H "Content-Type: application/json" -d '{"customer_id":"cust_demo_001"}'

curl -X POST http://localhost:8000/api/voice/sessions/<session_id>/turns \
  -H "Content-Type: application/json" \
  -d '{"transcript":"What happens if I miss a payment?","synthesize":false}'
```

With ElevenLabs configured, send `audio_base64` instead of `transcript` to use
speech-to-text, or set `synthesize` to `true` to receive base64-encoded MP3
audio. LiveKit/WebRTC streaming, VAD, interruption handling, and DTMF
protected collection remain the next voice milestone.

### Running Temporal Durable Workflows (M2)

Start a Temporal server with the `m2` compose profile, then run the worker:

```bash
docker compose --profile m2 up -d temporal
# worker in a terminal:
python -m taylor.orchestration.worker
# schedule an arrangement workflow in another:
python -m taylor.orchestration.client schedule \
  --arrangement-id ARR-001 --account-id ACC-001 \
  --amount 300.00 --date 2026-10-05 --action-id py-test-001
```

The workflows are:
- `PaymentArrangementWorkflow` — compliance gate → durable wait until the
  scheduled date → submit → reconcile UNKNOWN with durable backoff.
- `ReconcilePaymentWorkflow` — standalone recovery for actions stuck in UNKNOWN.

Workflow integration tests run hermetic against Temporal's time-skipping
test environment (no server needed):

```bash
TEMPORAL_INTEGRATION=1 pytest taylor/tests/test_orchestration.py -q
```

## Project Structure

```
agentic-servicing-platform/
├── marshall/          # FastAPI backend
├── taylor/            # LangGraph agent core
│   ├── graphs/        # Universal graph + subgraphs
│   ├── tools/         # Tool envelope, registry, and implementations
│   ├── runtime/       # Turn coordinator + text runtime
│   └── output/        # Deterministic output filter
├── mocks/             # Mock external services (FAC API, payment provider)
├── infra/             # Infrastructure configs (postgres, temporal, jaeger)
├── docs/              # Architecture docs + local running guide
├── evals/             # Deterministic evaluation cases and runner
├── frontend/          # React/TypeScript agent graph visualizer
├── .github/           # CI (pytest, ruff, frontend build)
└── docker-compose.yml
```

## Milestone Roadmap

| Milestone | Status | Description |
|---|---|---|
| M1 | ✅ | Core agent graph + tool architecture + state management |
| M2 | 🚧 In progress | **Compliance engine done** (stateless, strictest-wins, fail-closed); **Temporal durable workflows done** (payment arrangement + UNKNOWN reconciliation) |
| M3 | Planned | SMS channel (Twilio/webhook) |
| M4 | 🚧 In progress | **Web chat core + JWT identity + optional Redis sessions done**; reconnect handling and post-call analytics remain |
| M5 | 🚧 In progress | **ElevenLabs STT/TTS adapter + voice-session API done**; LiveKit/WebRTC streaming, VAD, interruption handling, and DTMF collection remain |
| M6 | 🚧 In progress | **Deterministic eval runner + privacy-aware turn traces done**; OpenTelemetry exporter configuration, dashboards, and broader model-quality evals remain |

## Parody Naming

All customer names are parodies. No real customer data is used.

| Parody | Replaces | Notes |
|---|---|---|
| FAC (Fictional Auto Credit) | Real auto-loan servicing API | Mock returns fake account data |
| Westpond | First tenant | Charged-off auto loans |
| CPR (Credit Payment Recovery) | Second tenant | Added later |
| Taylor | Agent core codename | Internal name, kept |
| Marshall | Backend codename | Internal name, kept |

## License

Personal project. All code is original. No proprietary code or data from any employer is included.
