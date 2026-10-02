# Agentic Servicing Platform — Technical Architecture Document

**Version:** 1.0  
**Date:** September 2026  
**Author:** Ian Lu  
**Status:** Milestone 1 Complete  

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [System Overview](#2-system-overview)
3. [Architecture Principles](#3-architecture-principles)
4. [Component Decomposition](#4-component-decomposition)
5. [Agent Graph Architecture](#5-agent-graph-architecture)
6. [Tool Architecture & Security Model](#6-tool-architecture--security-model)
7. [State Management & Reducers](#7-state-management--reducers)
8. [Sensitive Action State Machine](#8-sensitive-action-state-machine)
9. [Authorization Model](#9-authorization-model)
10. [Intent Router Design](#10-intent-router-design)
11. [Completion Gate & Evidence Chain](#11-completion-gate--evidence-chain)
12. [LLM Integration & Reasoning Engine](#12-llm-integration--reasoning-engine)
13. [Channel Architecture](#13-channel-architecture)
14. [Database & Persistence](#14-database--persistence)
15. [Output Filtering](#15-output-filtering)
16. [Compliance Handling](#16-compliance-handling)
17. [Observability](#17-observability)
18. [Testing Strategy](#18-testing-strategy)
19. [Deployment Topology](#19-deployment-topology)
20. [Roadmap](#20-roadmap)
21. [Appendix: File Inventory](#21-appendix-file-inventory)

---

## 1. Executive Summary

Agentic Servicing Platform is a production-style conversational AI system for regulated customer interactions. It demonstrates the architecture, programming logic, safety boundaries, and design patterns required to build an agent-native system where nondeterministic LLM reasoning operates inside deterministic code boundaries.

The system is built on a core principle: **the model interprets language and proposes actions; code decides whether actions are allowed, validates inputs, executes exactly once, records evidence, and decides what the customer may safely be told.**

### What's Implemented (Milestone 1)

| Capability | Status |
|---|---|
| LangGraph universal graph with 5 capability-scoped subgraphs | ✅ Operational |
| Tool envelope contract with server-derived identity | ✅ Operational |
| Tool registry with capability-based exposure | ✅ Operational |
| Sensitive action state machine (PROPOSED → CONFIRMED / UNKNOWN) | ✅ Operational |
| Versioned authorization artifacts | ✅ Operational |
| Intent router with channel + auth constraint validation | ✅ Operational |
| Evidence completion gate | ✅ Operational |
| LLM integration via OpenAI (reasoning engine + route-specific prompts) | ✅ Wired |
| Database persistence (SQLAlchemy async) | ✅ Wired |
| Mock FAC API with 3 fake accounts | ✅ Running |
| Mock payment provider with idempotency + timeout simulation | ✅ Running |
| Deterministic output filter | ✅ Operational |
| Interactive CLI | ✅ Operational |
| Test suite (252 collected; 247 passed, 5 skipped) | ✅ Passing |
| SMS channel (Twilio) | 📋 Milestone 3 |
| Web Chat channel | ✅ Core implemented (M4) |
| Voice channel (ElevenLabs adapter + session API) | 🚧 Core implemented (M5) |
| Temporal durable orchestration | ✅ Core implemented (M2) |
| Compliance engine (stateless, strictest-wins) | ✅ Core implemented (M2) |
| Observability (privacy-aware turn traces + OpenTelemetry API) | 🚧 Core implemented (M6) |

---

## 2. System Overview

### High-Level Architecture

```
customer input
     │
     ▼
channel ingress ──► identity/session boundary ──► turn coordinator
                                                    │
                              ┌─────────────────────┼─────────────────────┐
                              ▼                     ▼                     ▼
                       intent router          LLM reasoning         tool registry
                       (deterministic)        (nondeterministic)    (execution boundary)
                              │                     │                     │
                              └──────────────┬──────┴─────────────────────┘
                                             ▼
                                     validated action plan
                                             │
                              ┌──────────────┴──────────────┐
                              ▼                             ▼
                       sensitive-action gate          ordinary tool
                       (state machine)                (registry invoke)
                              │                             │
                              └──────────────┬──────────────┘
                                             ▼
                                      execution evidence
                                             │
                    completion gate ─► persist DB ─► output filter ─► reply
```

### Technology Stack

| Layer | Technology | Rationale |
|---|---|---|
| Agent Core (Taylor) | Python + LangGraph | Typed graph state, subgraphs, reducers, checkpointing |
| Backend (Marshall) | Python + FastAPI | Async, auto-docs, middleware support |
| LLM | OpenAI API (GPT-4o) | Tool calling, structured output, BYOK |
| Durable Orchestration | Temporal (self-hosted) | Workflow replay, timers, cross-channel arbitration |
| Database | PostgreSQL + SQLAlchemy async | Relational integrity, JSONB for flexible fields |
| Session Store | Redis | Low-latency session state for chat |
| SMS | Twilio | Webhook-based, delivery receipts |
| Voice | LiveKit (self-hosted) | Open-source WebRTC, agent integration |
| Observability | OpenTelemetry → Jaeger | Vendor-neutral tracing standard |
| Object Storage | MinIO | S3-compatible, local development |
| Deployment | Docker Compose | Local development, reproducible infrastructure |

---

## 3. Architecture Principles

These principles are enforced in code, not in prompts. A prompt may reduce error probability, but it cannot guarantee correctness.

### P1: Model Proposes, Code Executes

The LLM can only move a request to `PROPOSED`. Deterministic code controls normalization, validation, authorization, execution, and confirmation. This is enforced by the tool envelope contract (server-derived identity fields) and the state machine (model cannot skip states).

### P2: Capability-Based Tool Exposure

Execution tools are hidden from the model until their preconditions are met. This is enforced in the tool registry, not the prompt. The model cannot call a tool it cannot see.

### P3: UNKNOWN Is Not Failure

A timeout after submission is not the same as a failure. The system tells the customer confirmation is pending. A reconciliation worker queries provider status by idempotency key. This prevents ghost actions and double-charges.

### P4: Persist Before Success Language

Success language ("your payment has been scheduled") is only permitted after `CONFIRMED` is persisted to the database. The completion gate enforces this. For `UNKNOWN`, only "pending" language is allowed.

### P5: Versioned Authorization

Authorization is an artifact, not a boolean. It binds actor + amount + date + method + disclosures. If any bound field changes, the authorization is invalid and must be re-obtained. This prevents the model from modifying the action after consent.

### P6: Server-Derived Identity

The model cannot supply `customer_id`, `auth_level`, or `account_id`. These come from the authenticated session. The tool envelope enforces this separation: server-derived fields are in `ToolActor`, model-supplied fields are in `ToolIntent`.

### P7: Transcript Is Evidence, Not Source of Truth

Business state lives in normalized database fields with versioning and provenance. A model can mention a payment without creating one. A customer can correct a value after it appeared in the transcript.

### P8: File Config > DB Config > No Legacy Fallback

JSON config is baked into the Docker image. Changes require a tag rollout. File config beats DB config because it's immutable, versioned, and replayable. DB config can change at runtime without a deploy, which is dangerous in regulated systems.

### P9: Compliance Phrases Preempt All Routing

Bankruptcy, attorney, death, dispute — these trigger immediate compliance handoff before any other routing. This is checked in the router, before the LLM sees the utterance. A deterministic pre-model path handles legally significant keywords.

### P10: Channel Constraints Are Architectural

Chat cannot take payments. This is not a prompt instruction — it's enforced in the router's `CHANNEL_ROUTES` map and the tool registry's `set_channel_tools` override. The payment tools are literally unreachable from the chat channel.

---

## 4. Component Decomposition

### Taylor (Agent Core)

Taylor is the reasoning engine. It contains:

| Module | File | Responsibility |
|---|---|---|
| Graph State | `taylor/graphs/universal/state.py` | Four-category state model, typed reducers, enums |
| Intent Router | `taylor/graphs/universal/router.py` | Deterministic routing with channel + auth validation |
| Completion Gate | `taylor/graphs/universal/completion_gate.py` | Exit state validation, success language enforcement |
| Graph Builder | `taylor/graphs/universal/graph.py` | Assembles preconditions → router → subgraphs → gate |
| Knowledge Subgraph | `taylor/graphs/subgraphs/knowledge.py` | Read-only FAQ retrieval |
| Account Servicing | `taylor/graphs/subgraphs/account_servicing.py` | Scoped reads, allowlisted reversible updates |
| Arrangement | `taylor/graphs/subgraphs/arrangement.py` | Quote + validation, no side effects |
| Sensitive Action | `taylor/graphs/subgraphs/sensitive_action.py` | Protected collection, authorization, execution |
| Compliance Handoff | `taylor/graphs/subgraphs/compliance_handoff.py` | Policy evaluation, human transfer |
| Tool Envelope | `taylor/tools/envelope.py` | Server-derived identity, model-supplied intent |
| Tool Base Classes | `taylor/tools/base.py` | ReadTool, ProposalTool, ExecutionTool |
| Tool Registry | `taylor/tools/registry.py` | Capability-based exposure, single execution boundary |
| Read Tools | `taylor/tools/read_tools.py` | Account overview, payment methods, FAQ search |
| Proposal Tools | `taylor/tools/proposal_tools.py` | Payoff quote, payment proposal validation |
| Execution Tools | `taylor/tools/execution_tools.py` | Schedule payment, update phone, transfer to agent |
| LLM Client | `taylor/llm/client.py` | OpenAI async client, tool calling, classification |
| LLM Prompts | `taylor/llm/prompts.py` | Route-specific system prompts with constraints |
| Reasoning Engine | `taylor/llm/reasoning.py` | LLM + tool call loop, exit state determination |
| Turn Coordinator | `taylor/runtime/turn_coordinator.py` | Turn lifecycle, routing, reasoning, gate, persistence |
| Text Runtime | `taylor/runtime/text_runtime.py` | SMS/Chat runtime, config loading, history management |
| CLI | `taylor/runtime/cli.py` | Interactive conversation interface |
| Output Filter | `taylor/output/output_filter.py` | Word-boundary, case-preserving text transform |

### Marshall (Backend)

| Module | File | Responsibility |
|---|---|---|
| FastAPI App | `marshall/app/main.py` | Health endpoints, API entrypoint |
| Database | `marshall/core/database.py` | SQLAlchemy async ORM, persistence operations |

### Mock Services

| Service | File | Port | Purpose |
|---|---|---|---|
| Mock FAC API | `mocks/fac_api/app.py` | 9000 | Fake auto-loan account data |
| Mock Payment | `mocks/payment_provider.py` | 9001 | Deterministic payment processor with idempotency |

---

## 5. Agent Graph Architecture

### Graph Topology

```
START → preconditions → loop_budget_check → router → [route?] → subgraph → completion_gate → END
                                                         │
                                          ┌──────────────┼──────────────┐
                                          │              │              │
                                    knowledge       account_servicing  arrangement
                                          │              │              │
                              compliance_handoff  sensitive_action      │
                                          │              │              │
                                          └──────────────┴──────────────┘
                                                         │
                                                  completion_gate
                                                         │
                                                        END
```

### Subgraph Contracts

Each subgraph publishes a contract that the parent graph enforces:

| Subgraph | Allowed Inputs | Tool Authority | Required Exits |
|---|---|---|---|
| Knowledge | sanitized question, locale | read-only retrieval | cited_answer, no_answer |
| Account Servicing | authenticated account ref, requested field | read, execution (reversible only) | fresh_result, precondition_rejected, handoff |
| Arrangement | balance snapshot, customer proposal | proposal (quote/validate only) | validated_proposal, invalid_proposal |
| Sensitive Action | validated proposal, auth level, auth version | execution (protected collection + execute) | confirmed, rejected, cancelled, unknown_reconciling |
| Compliance Handoff | current action, channel, policy context | execution (transfer only) | policy_allow, policy_deny, transfer_accepted |

The parent graph validates every returned transition. A subgraph cannot:
- Route outside its declared destinations
- Widen its tool set
- Overwrite identity or policy context
- Return an exit state outside its contract

### Why Not Full Multi-Agent?

The system uses a **single graph with bounded subgraphs**, not independent agents communicating via messages. Rationale:

1. **Conversation is sequential within a turn.** Parallel agent reasoning has no benefit.
2. **Safety requires a single authoritative state owner.** Multiple agents competing to update state would break the proposal-authorization-execution chain.
3. **Coordination overhead has no payoff.** Message passing, conflict resolution, and consensus add complexity without value for a turn that takes seconds.

### Why Not a Pure Monolith?

1. **Tool surface explosion.** With 24 modules, exposing all tools in one prompt degrades model performance.
2. **Security isolation.** Different subgraphs need different tool allowlists and sensitive-data policies.
3. **Prompt interference.** A payment negotiation prompt and a FAQ retrieval prompt have materially different instructions.
4. **Evaluation.** Each subgraph can be tested independently with bounded fixtures and observable exit states.

### Agent Boundary Criteria

A capability deserves its own subgraph when it needs:
1. A distinct tool allowlist with different risk profiles
2. Different sensitive-data policy
3. A separate state schema
4. An independent evaluation set
5. A prompt whose size/instructions materially interfere with other work

---

## 6. Tool Architecture & Security Model

### Tool Envelope Contract

Every tool invocation carries a structured envelope:

```python
class ToolEnvelope(BaseModel):
    conversation_id: str        # server-derived
    turn_id: str                # server-derived
    action_id: str              # idempotency key (UUID, generated before external call)
    actor: ToolActor            # server-derived (customer_id, auth_level, account_id)
    intent: ToolIntent          # model-supplied (type, amount, date, method_token)
    authorization_ref: str      # versioned consent artifact ID
    policy_context_version: str # policy snapshot identifier
```

**Server-derived fields** (`conversation_id`, `turn_id`, `actor`) are populated by the turn coordinator from the authenticated session. The model cannot supply these.

**Model-supplied fields** (`intent.type`, `intent.amount`, `intent.date`, `intent.method_token`) are limited to business intent. The model expresses what it wants to do, not who it is or what authority it has.

### Tool Classification

| Class | Base Class | Side Effects | Auth Requirement | Visibility |
|---|---|---|---|---|
| Read | `ReadTool` | None | Authenticated session | Always available |
| Proposal | `ProposalTool` | None | Authenticated session | Available when preconditions met |
| Execution | `ExecutionTool` | Mutates state / calls provider | Step-up auth + authorization artifact | Hidden until preconditions met |

### Capability-Based Exposure

The registry's `get_visible_tools()` method filters tools based on:
1. **Channel override:** Chat channel cannot see `schedule_payment`
2. **Preconditions:** Execution tools require `action_status == AUTHORIZED`
3. **Tool class:** Read tools are always visible; proposal and execution tools require preconditions

This is enforced in the registry's code, not in the prompt. The model cannot call a tool it cannot see.

### The Registry as Execution Boundary

All tool invocations go through `registry.invoke()`, which:
1. Checks the tool exists
2. Checks preconditions are met
3. For execution tools, validates authorization (step-up auth + authorization_ref)
4. Executes the tool
5. Returns a `ToolResult` with a stable status taxonomy

No code path exists for the model to bypass the registry.

### Tool Result Status Taxonomy

| Status | Meaning | Customer Language |
|---|---|---|
| `confirmed` | Provider confirmed the action | Success language allowed |
| `rejected` | Provider or validation rejected | Failure language allowed |
| `retryable_failure` | Transient error, can retry | "Let me try that again" |
| `unknown` | Timeout after submission, reconciliation needed | "Pending confirmation" only |
| `invalid_request` | Missing/invalid fields or auth | "I can't do that" |

### Registered Tools (Milestone 1)

| Tool | Class | Purpose |
|---|---|---|
| `get_account_overview` | Read | Fetch balance, due date, status from FAC API |
| `get_payment_methods` | Read | List saved payment methods (tokens only) |
| `search_faq` | Read | Keyword search over mock knowledge base |
| `calculate_payoff_quote` | Proposal | Compute payoff amount for a date |
| `validate_payment_proposal` | Proposal | Check amount/date/method rules, return normalized proposal |
| `schedule_payment` | Execution | Submit payment to mock provider (requires authorization) |
| `update_phone_number` | Execution | Update contact info (requires authorization) |
| `transfer_to_agent` | Execution | Human handoff (always available) |

---

## 7. State Management & Reducers

### Four-Category State Model

| Category | Examples | Lifecycle |
|---|---|---|
| Turn State | utterance, detected_intent, tool_request | Ephemeral; retained in trace |
| Session State | conversation_id, auth_level, collected_slots, pending_confirmation | Conversation runtime; versioned, checkpointed |
| Business State | account_balance, due_date, payment_status | System of record or durable workflow |
| Protected State | credential_token, authorization_artifact | Isolated vault; never in graph messages or prompts |

### Reducer Semantics

| Field | Redducer | Rationale |
|---|---|---|
| Messages | Append-only (`add_messages`) | Never lose conversational context |
| `collected_slots` | Merge (union of keys, right wins) | Accumulate information without losing prior |
| `pending_confirmation` | Compare-and-set (version-based) | Prevent race between correction and execution |
| `selected_payment_method` | Replace (right always wins, including None) | New selection invalidates old |

### Compare-and-Set Race Prevention

The `pending_confirmation` reducer prevents a critical race:

```
Timeline:
  t1: Customer confirms $300 (version=1)
  t2: Customer corrects to $350 (version=2) — CAS accepts, v2 > v1
  t3: Stale execution result arrives with version=1 — CAS rejects, v1 < v2
```

Without compare-and-set, the stale execution result would overwrite the correction, and the customer would be charged $300 instead of the corrected $350.

### Store-Level Ownership Map

| Store | Authoritative For | NOT Authoritative For |
|---|---|---|
| Graph checkpoint | Resumable node/edge position | Completed business actions |
| Session store | Channel connection, auth context | Account balance, policy outcome |
| Durable workflow | Journey state, timers, orchestration | Raw credentials, unconfirmed claims |
| System of record | Account facts, confirmed mutations | What the customer was told |
| Audit store | Immutable evidence, traces | Command authority, live state |

---

## 8. Sensitive Action State Machine

```
PROPOSED → NORMALIZED → VALIDATED → AUTHORIZED → EXECUTING → CONFIRMED
                ↘ REJECTED              ↘ UNKNOWN
                                       
UNKNOWN → (reconciliation) → CONFIRMED or REJECTED
```

### State Definitions

| State | Who Controls | Meaning |
|---|---|---|
| PROPOSED | Model | Model inferred an intent |
| NORMALIZED | Code | Amounts, dates, IDs have canonical types |
| VALIDATED | Code | Business constraints and policy accept values |
| AUTHORIZED | Customer | Customer approved the exact normalized action |
| EXECUTING | Code | Idempotent external request has begun |
| CONFIRMED | Provider | Authoritative provider response persisted |
| REJECTED | Code/Provider | Action denied or failed |
| UNKNOWN | Code | Timeout after submission — reconciliation required |

### Key Rules

1. **The model can only reach `PROPOSED`.** All subsequent transitions are controlled by deterministic code.
2. **`UNKNOWN` is not `REJECTED`.** The agent says "confirmation is pending," not "it failed" or "it succeeded."
3. **Success language requires `CONFIRMED`.** The completion gate checks `action_status == CONFIRMED` before allowing success phrasing.
4. **`action_id` is the idempotency key.** Generated before the external call, persisted, and used for reconciliation.

---

## 9. Authorization Model

Authorization is a **versioned artifact**, not a boolean. It binds:

| Field | Example | Invalidation Condition |
|---|---|---|
| Actor | `{customer_id: "cust-001", auth_level: "step_up"}` | If customer_id changes |
| Amount | `"300.00"` | If amount changes |
| Date | `"2026-09-15"` | If date changes |
| Method Token | `"pm_tok_001"` | If method_token changes |
| Action Type | `"schedule_payment"` | If action type changes |
| Disclosures | `{amount_disclosed: true, ...}` | If disclosures change |
| Version | `1` | Incremented on each new authorization |

If any bound field changes after consent, the authorization is **invalid** and must be re-obtained. This prevents:
- The model changing the amount after the customer said "yes" to $300
- Reusing a payment authorization for a different payment
- A corrected date silently invalidating consent

---

## 10. Intent Router Design

### Architecture

The router is **deterministic entry with classifier assistance**:

1. Read authenticated session state and current utterance
2. Check for compliance phrases (preempt all routing)
3. Classify intent (regex patterns in M1, LLM-assisted in production)
4. Validate the proposed route against allowed transitions for this channel + auth level
5. Fall back to knowledge subgraph if invalid or ambiguous

### Channel Constraints

```python
CHANNEL_ROUTES = {
    "sms": {knowledge, account_servicing, arrangement, sensitive_action, compliance_handoff},
    "chat": {knowledge, account_servicing, arrangement, compliance_handoff},
    # NOTE: sensitive_action intentionally excluded from chat
    "voice": {knowledge, account_servicing, arrangement, sensitive_action, compliance_handoff},
}
```

### Auth Requirements

```python
AUTH_REQUIREMENTS = {
    "knowledge": ANONYMOUS,       # FAQ is public
    "account_servicing": VERIFIED,
    "arrangement": VERIFIED,
    "sensitive_action": STEP_UP,  # Requires step-up authentication
    "compliance_handoff": ANONYMOUS,
}
```

### Pattern Ordering

Patterns are checked in priority order:
1. Compliance phrases (bankruptcy, attorney, death, dispute) — highest priority
2. Transfer requests (human, agent, representative)
3. Arrangement (settlement, payment plan, payoff)
4. Account servicing (balance, update, change)
5. Knowledge (question words at start of sentence)
6. Sensitive action (pay, payment, charge, card)
7. Knowledge (fallback question patterns)

This ordering ensures "What happens if I miss a payment?" routes to knowledge (not sensitive_action) and "I need a payment plan" routes to arrangement (not sensitive_action).

---

## 11. Completion Gate & Evidence Chain

### Purpose

The completion gate is the final deterministic check before a response reaches the customer. It validates:

1. **Exit state validity:** The subgraph returned one of its declared exit states
2. **Success language permission:** Whether the response may include success claims

### Success Language Rules

| Route | Action Status | Success Language |
|---|---|---|
| sensitive_action | CONFIRMED | ✅ Allowed |
| sensitive_action | UNKNOWN | ❌ Blocked — "pending" only |
| sensitive_action | EXECUTING | ❌ Blocked |
| sensitive_action | REJECTED | ❌ Blocked — failure only |
| knowledge | cited_answer | ✅ Allowed |
| knowledge | no_answer | ❌ Blocked |
| account_servicing | fresh_result | ✅ Allowed |
| arrangement | validated_proposal | ✅ Allowed |
| compliance_handoff | transfer_accepted | ✅ Allowed |

If the gate fails, the reply is overridden to: "I'm sorry, I couldn't complete that action. Let me transfer you to an agent."

---

## 12. LLM Integration & Reasoning Engine

### Architecture

The reasoning engine handles the agent loop:

```
1. Get visible tools for current state + channel
2. Call LLM with system prompt + user message + tool schemas
3. If LLM returns tool calls:
   a. Build tool envelope (server-derived fields from session)
   b. Execute through registry (the security boundary)
   c. Track action status and result
   d. Feed tool results back to LLM
   e. Repeat (up to max_tool_attempts)
4. LLM returns final text response
5. Determine exit state based on route + action status
6. Return response + exit state + action result
```

### System Prompts

Each route gets a tailored system prompt containing:

1. **Base instructions:** Agent identity, output filter rules, general behavior
2. **Auth context:** What the customer can and cannot do at their auth level
3. **Channel context:** Channel-specific constraints (chat can't take payments)
4. **Route-specific instructions:** What tools to use and how to behave

### Error Handling

If the LLM call fails (network error, quota exhaustion, timeout), the reasoning engine returns a `HANDOFF` exit state. The completion gate then produces a safe "transfer to agent" response. The system never exposes raw error messages to the customer.

---

## 13. Channel Architecture

### SMS (Milestone 3 — Planned)

- Twilio webhook handler for inbound + delivery receipts
- Coalescing: 2.5s quiet window, max ~8s or 5 messages → one model turn
- Deterministic pre-model path for STOP/opt-out/compliance keywords
- Outbound pipeline: plan → approval → compliance gate → send
- Event ID deduplication

### Web Chat (Milestone 4 — Core implemented)

- Local demo widget with FastAPI session, message, and history endpoints
- Server-derived identity and bounded in-process session state
- Narrow tool surface (no payment execution — architectural)
- `$0.00` anti-pattern prevention
- JWT identity boundary and optional Redis-backed session storage
- Remaining: reconnect handling and post-call analytics

### Voice (Milestone 5 — Core adapter implemented)

- Marshall voice sessions with server-derived identity
- ElevenLabs speech-to-text adapter
- ElevenLabs text-to-speech adapter
- Transcript-only deterministic path for free local testing
- LiveKit server reserved for the real-time transport boundary
- VAD + endpointing (balance responsiveness vs truncation)
- Interruption handling (cancel in-flight model + stop TTS)
- Protected collection: pause transcription, DTMF digit capture, opaque token
- Progress phrases only during tool calls; suppress success language until CONFIRMED
- Disconnect-during-execution: durable action continues, later channel presents outcome

---

## 14. Database & Persistence

### Schema

| Table | Purpose | Key Fields |
|---|---|---|
| `tool_actions` | Execution evidence chain | action_id (idempotency key), status, intent, provider_response |
| `authorization_artifacts` | Versioned consent | artifact_id, bound_values, is_valid, version |
| `sessions` | Conversation runtime state | conversation_id, auth_level, collected_slots |
| `audit_events` | Immutable evidence | conversation_id, turn_id, event_type, event_data |

### Persistence Flow

After each turn, the turn coordinator persists:
1. **Session record** (upsert): conversation_id, auth_level, channel, collected_slots
2. **Tool actions** (insert): one per tool call, with action_id and status
3. **Authorization artifacts** (insert): if any were created during the turn
4. **Audit event** (insert): route, exit_state, action_status, reply, tool calls, usage

Database persistence is non-fatal — if the DB is unavailable, the turn still completes. This is a pragmatic choice for development; production would require strict persistence before success language.

---

## 15. Output Filtering

### Design

The output filter is a deterministic text transform in code, not a prompt instruction:

- **Word-boundary-aware:** Does not rewrite "loan" inside "loanable"
- **Case-preserving:** "Loan" → "Contract", "LOAN" → "CONTRACT", "loan" → "contract"
- **Streaming-safe:** Works on partial text chunks
- **Configurable:** Replacement map loaded from graph config

### Default Replacements

| Original | Replacement |
|---|---|
| loan | contract |
| loans | contracts |
| lender | creditor |
| borrower | customer |

### Why Code, Not Prompt?

A prompt can ask the model not to say "loan," but it cannot guarantee it. The output filter guarantees the customer never sees "loan" regardless of what the model generates. The filter runs after the LLM response and before the reply is sent.

---

## 16. Compliance Handling

### Design (M1 Router Preemption)

Compliance phrases are detected in the router, before the LLM sees the utterance:

```python
COMPLIANCE_PHRASES = [
    "death", "deceased", "bankruptcy", "bankrupt",
    "attorney", "lawyer", "legal counsel",
    "dispute", "not my debt", "identity theft", "cease and desist",
]
```

When detected, the router preempts all other routing and sends the conversation to the compliance_handoff subgraph, which initiates a human transfer.

### Design (M2 — Implemented Compliance Engine)

The full compliance engine will be:
- **Stateless:** Pure function of (account state, proposed action, time, rules)
- **Strictest-wins:** When multiple rules apply, the most restrictive outcome wins
- **Fail-closed:** If the engine can't determine compliance, it denies
- **Never initiates:** Compliance only blocks, never triggers

Implemented rules include:
- Terminal account status (settled, cease-and-desist, bankruptcy, legal)
- Channel opt-outs (SMS, voice, DNC)
- Consent verification
- Outbound time windows (TCPA)
- Daily and cumulative contact caps
- State-level SMS exclusions
- Cross-channel constraints (no SMS after connected call, etc.)

---

## 17. Observability

### M6 core implementation

| Signal | Tool | Purpose |
|---|---|---|
| Traces | OpenTelemetry → Jaeger | How one customer turn crossed components |
| Metrics | Prometheus | How often and how long |
| Audit | PostgreSQL audit_events | Who authorized what under which policy |
| Logs | Structured (structlog) | What happened at one component |

The runtime now emits a privacy-aware lifecycle trace for each turn:
`turn.started → turn.routed → turn.reasoned → turn.gate_checked → turn.finished`.
The trace carries conversation and turn correlation IDs, route, gate outcome,
tool-call count, usage metadata, and duration. It records an utterance fingerprint
instead of raw text and redacts protected-looking fields. A local JSONL sink is
available for development; the OpenTelemetry API remains vendor-neutral and can
be connected to an OTLP exporter or Jaeger collector.

### Correlation Model

| ID | Generated By | Purpose |
|---|---|---|
| Journey ID | Durable workflow | One per account journey (weeks) |
| Conversation ID | Channel adapter | One per conversation |
| Turn ID | Turn coordinator | One per customer turn |
| Action ID | Tool envelope | One per tool invocation (idempotency key) |
| Provider Request ID | Provider adapter | One per external API call |
| Deploy Bundle | CI/CD | Code + config + prompt + model version |

All IDs are generated at trusted boundaries and propagated, never parsed from free text or model output.

---

## 18. Testing Strategy

### Test Categories

| Category | File | Coverage |
|---|---|---|---|
| Core state and graph boundaries | `test_state.py`, `test_graph.py`, `test_subgraphs.py` | Reducers, transitions, routing, contracts, completion gate |
| Tool and policy boundaries | `test_envelope.py`, `test_registry.py`, `test_compliance.py` | Identity, idempotency, exposure, authorization, fail-closed compliance |
| Channels and orchestration | `test_chat_channel.py`, `test_orchestration.py` | Session lifecycle, chat restrictions, durable timers, UNKNOWN reconciliation |
| Routing, output, and evals | `test_router.py`, `test_output_filter.py`, `test_eval_suite.py` | Classification, filtering, regression cases |
| **Full suite** | | **252 collected; 247 passed, 5 skipped** |

### Design Principle

Tests mirror the architecture — each component tested in isolation with bounded fixtures and observable exit states. Layered gates: deterministic tests first, focused model evals, broader regression, then shadow/canary.

---

## 19. Deployment Topology

### Docker Compose Services

| Service | Port | Milestone | Status |
|---|---|---|---|
| postgres | 5432 | M1 | ✅ Configured |
| redis | 6379 | M1 | ✅ Configured |
| mock-fac | 9000 | M1 | ✅ Running |
| mock-payment | 9001 | M1 | ✅ Running |
| jaeger | 16686 | M6 | ✅ Configured |
| temporal | 7233, 8080 | M2 | 📋 Profile: m2 |
| minio | 9002, 9003 | M4 | 📋 Profile: m4 |
| livekit | 7880 | M5 | 📋 Profile: m5 |

### Configuration Precedence

```
file-backed JSON config (baked into image)
    > database config
        > legacy code fallback (none for chat)
```

Config is loaded from `taylor/graphs/universal/graph_configs/default_en.json`. Changes require a Docker image tag rollout. This ensures immutability and reproducibility.

---

## 20. Roadmap

| Milestone | Scope | Key Deliverables |
|---|---|---|
| M1 ✅ | Core agent + tools + state | LangGraph, tool registry, state machine, mock services |
| M2 🚧 | Compliance + Temporal | Compliance engine and durable workflows implemented; cross-channel arbitration and replay tests remain |
| M3 | SMS channel | Twilio webhooks, coalescing, outbound pipeline, compliance keywords |
| M4 🚧 | Web Chat | Local widget/API, JWT identity, and optional Redis sessions implemented; reconnect handling and post-call processing remain |
| M5 🚧 | Voice | ElevenLabs STT/TTS adapter and turn API implemented; LiveKit, VAD, DTMF protected collection, and interruption handling remain |
| M6 🚧 | Observability + Evals | Deterministic eval runner and privacy-aware turn traces implemented; dashboards, OTLP export, model-quality evals, and evidence bundles remain |

---

## 21. Appendix: File Inventory

```
agentic-servicing-platform/
├── .env.example
├── .gitignore
├── README.md
├── pyproject.toml
├── docker-compose.yml
│
├── marshall/
│   ├── __init__.py
│   ├── app/
│   │   ├── __init__.py
│   │   └── main.py
│   ├── core/
│   │   ├── __init__.py
│   │   └── database.py
│   └── tests/
│
├── taylor/
│   ├── __init__.py
│   ├── graphs/
│   │   ├── __init__.py
│   │   ├── universal/
│   │   │   ├── __init__.py
│   │   │   ├── state.py
│   │   │   ├── router.py
│   │   │   ├── completion_gate.py
│   │   │   ├── graph.py
│   │   │   └── graph_configs/
│   │   │       └── default_en.json
│   │   └── subgraphs/
│   │       ├── __init__.py
│   │       ├── knowledge.py
│   │       ├── account_servicing.py
│   │       ├── arrangement.py
│   │       ├── sensitive_action.py
│   │       └── compliance_handoff.py
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── envelope.py
│   │   ├── base.py
│   │   ├── registry.py
│   │   ├── read_tools.py
│   │   ├── proposal_tools.py
│   │   └── execution_tools.py
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── client.py
│   │   ├── prompts.py
│   │   └── reasoning.py
│   ├── runtime/
│   │   ├── __init__.py
│   │   ├── turn_coordinator.py
│   │   ├── text_runtime.py
│   │   └── cli.py
│   ├── output/
│   │   ├── __init__.py
│   │   └── output_filter.py
│   └── tests/
│       ├── __init__.py
│       ├── conftest.py
│       ├── test_state.py
│       ├── test_envelope.py
│       ├── test_registry.py
│       ├── test_router.py
│       ├── test_output_filter.py
│       ├── test_subgraphs.py
│       └── test_graph.py
│
├── mocks/
│   ├── __init__.py
│   ├── fac_api/
│   │   ├── __init__.py
│   │   ├── app.py
│   │   ├── Dockerfile
│   │   └── data/
│   │       └── accounts.json
│   ├── payment_provider.py
│   └── Dockerfile.payment
│
├── infra/
│   ├── postgres/
│   │   └── init.sql
│   ├── temporal/
│   └── jaeger/
│
└── evals/
    ├── __init__.py
    ├── router_evals/
    ├── tool_evals/
    ├── policy_evals/
    └── conversation_evals/
```

**Current validation: 252 tests collected, 247 passed, 5 skipped.**

---

*End of document.*
