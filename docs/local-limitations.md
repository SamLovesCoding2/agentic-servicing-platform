# Agentic Servicing Platform — Local Running Guide & Limitations

**Date:** September 2026  
**Goal:** Run everything locally for free, without any paid external services.

---

## Quick Start

```bash
cd /Users/ianlu/agentic-servicing-platform
./start.sh
```

This script:
1. Creates a virtual environment (if needed)
2. Installs dependencies (if needed)
3. Starts Docker containers for mock services
4. Runs the 222-test Taylor core suite
5. Launches the interactive CLI

**Prerequisites:** Docker Desktop (free). No paid accounts needed.

---

## What Works Locally for Free

| Capability | Status | How to Use |
|---|---|---|
| **Full test suite** | ✅ 247 passed, 5 skipped | `pytest -v` |
| **Mock FAC API** | ✅ Running in Docker | `curl http://localhost:9000/accounts/ACC-001/overview` |
| **Mock Payment Provider** | ✅ Running in Docker | `curl http://localhost:9001/health` |
| **Agent routing** | ✅ Fully working | CLI or tests — router classifies intents correctly |
| **Tool registry & capability-based exposure** | ✅ Fully working | Tests verify execution tools hidden until preconditions met |
| **State machine (PROPOSED → CONFIRMED / UNKNOWN)** | ✅ Fully working | Tests verify all transitions |
| **Completion gate (success language enforcement)** | ✅ Fully working | Tests verify UNKNOWN blocks success language |
| **Versioned authorization artifacts** | ✅ Fully working | Tests verify invalidation on field change |
| **Output filter (loan → contract)** | ✅ Fully working | Tests verify word-boundary, case-preserving |
| **Interactive CLI (deterministic mode)** | ✅ Fully working | `python -m taylor.runtime.cli --no-llm` |
| **Agent graph visualizer** | ✅ Fully working | Open `frontend/index.html` in any browser |
| **PostgreSQL** | ✅ Running in Docker | `localhost:5432` (user: agentic_platform, db: agentic_platform) |
| **Redis** | ✅ Running in Docker | `localhost:6379` |
| **Jaeger (traces UI)** | ✅ Running in Docker | `http://localhost:16686` |
| **Deterministic eval runner** | ✅ Fully working | `python -m evals.runner --cases evals/cases.json` |
| **Privacy-aware turn traces** | ✅ Fully working | Set `TRACE_JSONL_PATH=./var/traces.jsonl` |
| **Voice transcript turns** | ✅ Fully working | `POST /api/voice/sessions/{id}/turns` with `transcript` |
| **ElevenLabs STT/TTS adapter** | ✅ Tested without network | Configure `ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID` |
| **JWT identity boundary** | ✅ Fully working | Set `AUTH_MODE=jwt`; use `Authorization: Bearer <token>` |
| **Redis session backend** | ✅ Implemented | Set `SESSION_STORE=redis` and start Redis |

---

## What Requires Money

| Capability | What's Needed | Cost | Workaround |
|---|---|---|---|
| **LLM-powered responses** | OpenAI API credits | $5-20/mo for testing | Use `--no-llm` flag for deterministic mode (predefined responses, routing still works) |
| **Real SMS messages** | Twilio account | $15/mo + per-message | Not yet implemented (M3). Mock webhook receiver included. |
| **ElevenLabs audio** | ElevenLabs API key and voice ID | Usage-based | Transcript-only mode is free and deterministic |
| **Real-time voice calls** | LiveKit + WebRTC transport | Varies | LiveKit/VAD/interruptions remain in M5 |

**Bottom line:** You can run the entire system locally for $0. The only thing that costs money is making the LLM generate intelligent responses instead of deterministic stubs. Everything else — routing, safety boundaries, tools, state machine, tests, visualizer — works for free.

---

## What's Not Yet Implemented

| Milestone | What's Missing | Target |
|---|---|---|
| **M2: Compliance Engine + Temporal** | Cross-channel arbitration and replay tests remain; core engine and workflows are implemented | In progress |
| **M3: SMS Channel** | Twilio webhook handler, inbound coalescing, outbound pipeline, compliance keyword detection | Future |
| **M4: Web Chat** | Reconnect handling and post-call processing remain; JWT identity and Redis sessions are implemented | In progress |
| **M5: Voice** | ElevenLabs adapter and turn API are implemented; LiveKit/WebRTC, VAD, DTMF protected collection, and interruption handling remain | In progress |
| **M6: Observability + Evals** | Deterministic eval runner and privacy-aware traces are implemented; dashboards, OTLP export, and model-quality evals remain | In progress |

---

## How to Use Each Component

### Run Tests
```bash
cd /Users/ianlu/agentic-servicing-platform
source .venv/bin/activate
pytest -v                          # 247 passed, 5 skipped
pytest taylor/tests/test_router.py -v   # just router tests
pytest taylor/tests/test_state.py -v    # just state/reducer tests
```

### Interactive CLI (deterministic mode — no API key needed)
```bash
python -m taylor.runtime.cli --no-llm --debug
```

### JWT and Redis mode
```bash
AUTH_MODE=jwt SESSION_STORE=redis uvicorn marshall.app.main:app --port 8000
```

The local-only demo endpoint can mint a token while `AUTH_MODE=demo`:
```bash
curl -X POST http://localhost:8000/api/auth/demo-token \
  -H "Content-Type: application/json" \
  -d '{"customer_id":"cust_demo_001","tenant_id":"demo"}'
```
The demo token endpoint is disabled when `AUTH_MODE=jwt`. In JWT mode, session
creation and all session reads/writes require a bearer token, and customer plus
tenant mismatches return `404` to avoid leaking session existence.

### Evaluation runner
```bash
python -m evals.runner --cases evals/cases.json --fail-under 1.0
```

The runner is deterministic and free to execute. It reports pass rate by category
and exits non-zero when the configured threshold is not met.

### Local trace capture
```bash
TRACE_JSONL_PATH=./var/traces.jsonl \
  MARSHALL_LLM_ENABLED=0 \
  uvicorn marshall.app.main:app --port 8000
```

Trace records contain correlation IDs, routing, gate decisions, tool counts, usage
metadata, and duration. Raw utterances and protected tokens are excluded.

### Voice channel
```bash
# Free transcript-only path
curl -X POST http://localhost:8000/api/voice/sessions \
  -H "Content-Type: application/json" -d '{"customer_id":"cust_demo_001"}'

curl -X POST http://localhost:8000/api/voice/sessions/<session_id>/turns \
  -H "Content-Type: application/json" \
  -d '{"transcript":"What is my balance?","synthesize":false}'
```

Set `ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID` to enable audio transcription
and MP3 synthesis. The current adapter is request/response based; the LiveKit
real-time transport is not yet implemented.
Commands within the CLI:
- `/auth step_up` — upgrade to step-up auth (unlocks sensitive actions)
- `/channel chat` — switch to chat channel (blocks payment execution)
- `/account ACC-002` — switch to a different account
- `/tools` — show which tools are visible for your current state
- `/quit` — exit

### Interactive CLI (LLM mode — needs OpenAI credits)
```bash
# Add your API key to .env first
echo "OPENAI_API_KEY=sk-your-key" >> .env
python -m taylor.runtime.cli --debug
```

### Agent Graph Visualizer
```bash
open /Users/ianlu/agentic-servicing-platform/frontend/index.html
```
- Click any node to see its contract, tools, and description
- Use the Route Simulator (top-left) to test how utterances route
- Try: "I want to pay $300" with channel=chat vs channel=sms
- Try: "I'm filing for bankruptcy" (any channel — should route to compliance)
- Drag to pan, scroll to zoom

### Mock FAC API (fake auto-loan data)
```bash
# Get account overview
curl http://localhost:9000/accounts/ACC-001/overview

# Get payment methods
curl http://localhost:9000/accounts/ACC-001/payments

# Schedule a mock payment
curl -X POST http://localhost:9000/accounts/ACC-001/payments \
  -H "Content-Type: application/json" \
  -d '{"amount":"<AMOUNT>","date":"<YYYY-MM-DD>","method_token":"<opaque-token>","action_id":"<ACTION_ID>"}'
```

### Mock Payment Provider (deterministic, with idempotency)
```bash
# Submit a payment (deterministic by action_id)
curl -X POST http://localhost:9001/payments/submit \
  -H "Content-Type: application/json" \
  -d '{"action_id":"<ACTION_ID>","account_id":"ACC-001","amount":"<AMOUNT>","date":"<YYYY-MM-DD>","method_token":"<opaque-token>"}'

# Check status (reconciliation)
curl http://localhost:9001/payments/status/test-001
```

### Start/Stop Docker Services
```bash
# Start everything
docker compose up -d mock-fac mock-payment postgres redis jaeger

# Stop everything
docker compose down

# Check status
docker compose ps
```

---

## Architecture: What's Running

```
Your Machine (Docker)
├── mock-fac (port 9000)        ← Fake auto-loan API
├── mock-payment (port 9001)    ← Fake payment processor
├── postgres (port 5432)        ← Database for persistence
├── redis (port 6379)           ← Session store (for M4 chat)
└── jaeger (port 16686)         ← Trace visualization (for M6)

Your Machine (Python)
├── Taylor Agent Core           ← LangGraph, tools, state machine
├── CLI                         ← Interactive conversation interface
└── 252 collected tests         ← 247 passed, 5 skipped

Your Browser
└── Agent Visualizer            ← Interactive graph view (frontend/index.html)
```

---

## FAQ

**Q: Can I have a real conversation with the agent without paying for OpenAI?**
A: Not yet. In deterministic mode, the agent gives predefined responses based on the route. The routing, safety boundaries, and tool architecture all work — but the responses are canned. Add $5 to your OpenAI account and put the key in `.env` to get intelligent LLM-powered responses.

**Q: Can I receive real SMS messages?**
A: Not yet. SMS channel implementation is Milestone 3. The mock SMS provider is included for testing the webhook handler when it's built.

**Q: Can I use voice locally?**
A: Yes, with transcript-only turns at no cost. ElevenLabs STT/TTS requires
credentials. Full real-time calls still require the planned LiveKit transport.

**Q: Does the database work?**
A: PostgreSQL runs in Docker and the schema is created on startup. The turn coordinator persists sessions, tool actions, authorization artifacts, and audit events. However, database persistence is non-fatal — if PostgreSQL is down, the system still works (it just doesn't persist).

**Q: Can I deploy this to the cloud?**
A: The system is designed for local development with Docker Compose. Cloud deployment would require replacing Docker Compose with your cloud's container orchestration (ECS, Cloud Run, Kubernetes) and using managed PostgreSQL, Redis, and Temporal. The architecture is cloud-ready; the infrastructure config is local-only.

**Q: How do I add a new tool?**
A: Create a class inheriting from `ReadTool`, `ProposalTool`, or `ExecutionTool` in `taylor/tools/`. Implement the `execute()` method. Register it in `taylor/runtime/text_runtime.py` in the `build_tool_registry()` function. If it's an execution tool, add preconditions to control when it becomes visible to the model.

**Q: How do I add a new subgraph?**
A: Create a new file in `taylor/graphs/subgraphs/`. Define the graph nodes, edges, and a contract dict. Add it to the main graph in `taylor/graphs/universal/graph.py`. Add the route to `taylor/graphs/universal/router.py` with appropriate channel and auth constraints. Add a system prompt in `taylor/llm/prompts.py`.

---

*End of document.*
