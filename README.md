# Salient Replica

A functional replica of a production conversational AI system for regulated customer interactions. Built with deterministic safety boundaries around nondeterministic LLM reasoning.

[![CI — Backend](https://github.com/SamLovesCoding2/salient-replica/actions/workflows/ci.yml/badge.svg?job=backend)](https://github.com/SamLovesCoding2/salient-replica/actions/workflows/ci.yml)
[![CI — Frontend](https://github.com/SamLovesCoding2/salient-replica/actions/workflows/ci.yml/badge.svg?job=frontend)](https://github.com/SamLovesCoding2/salient-replica/actions/workflows/ci.yml)

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
git clone <your-repo-url> salient-replica
cd salient-replica

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

### Running the Mock Services Standalone

```bash
# Mock FAC API (port 9000)
python -m mocks.fac_api.app

# Mock Payment Provider (port 9001)
python -m mocks.payment_provider
```

## Project Structure

```
salient-replica/
├── marshall/          # FastAPI backend
├── taylor/            # LangGraph agent core
│   ├── graphs/        # Universal graph + subgraphs
│   ├── tools/         # Tool envelope, registry, and implementations
│   ├── runtime/       # Turn coordinator + text runtime
│   └── output/        # Deterministic output filter
├── mocks/             # Mock external services (FAC API, payment provider)
├── infra/             # Infrastructure configs (postgres, temporal, jaeger)
├── docs/              # Architecture docs + local running guide
├── evals/             # Evaluation framework (M6+)
├── frontend/          # React/TypeScript agent graph visualizer
├── .github/           # CI (pytest, ruff, frontend build)
└── docker-compose.yml
```

## Milestone Roadmap

| Milestone | Status | Description |
|---|---|---|
| M1 | ✅ Current | Core agent graph + tool architecture + state management |
| M2 | Planned | Compliance engine + Temporal durable orchestration |
| M3 | Planned | SMS channel (Twilio/webhook) |
| M4 | Planned | Web Chat channel (browser widget + JWT auth) |
| M5 | Planned | Voice channel (LiveKit + ASR/TTS) |
| M6 | Planned | Observability + evaluation framework |

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
