import type { GraphNode, GraphEdge, MilestoneItem, ImplItem } from "./types";

export const NODES: GraphNode[] = [
  {
    id: "START", label: "START", type: "control", x: 400, y: 40, r: 18, color: "#6e7681",
    desc: "Entry point for every conversation turn.",
  },
  {
    id: "preconditions", label: "Preconditions", type: "control", x: 400, y: 105, r: 20, color: "#8957e5",
    desc: "Validates conversation_id, customer_id, channel, and turn budget. If any are missing, routes to safe handoff.",
  },
  {
    id: "loop_budget", label: "Loop Budget", type: "control", x: 400, y: 170, r: 20, color: "#8957e5",
    desc: "Checks max_model_turns (10), max_tool_attempts (5), and max_elapsed_seconds (30). Rejects if exceeded.",
  },
  {
    id: "router", label: "Intent Router", type: "control", x: 400, y: 245, r: 24, color: "#8957e5",
    desc: "Deterministic entry with classifier assistance. Checks compliance phrases first (preempt), then classifies intent, validates route against channel + auth constraints. Falls back to knowledge if invalid.",
    rules: [
      "Compliance phrases (bankruptcy, attorney, death, dispute) → preempt to compliance_handoff",
      "Chat channel cannot route to sensitive_action (architectural constraint)",
      "Sensitive action requires step_up auth",
      "Account servicing requires verified auth",
      "Knowledge is the safe default fallback",
    ],
  },
  {
    id: "knowledge", label: "Knowledge", type: "subgraph", x: 120, y: 370, r: 30, color: "#2ea043",
    desc: "Read-only retrieval. Answers FAQs and policy questions with citations. Cannot write any state except an answer draft.",
    contract: {
      allowed_inputs: ["sanitized question", "locale"],
      writable_state: ["answer draft", "citations"],
      tool_authority: ["read-only retrieval"],
      required_exits: ["cited_answer", "no_answer"],
    },
    tools: ["search_faq"],
  },
  {
    id: "account_servicing", label: "Account\nServicing", type: "subgraph", x: 280, y: 370, r: 30, color: "#2ea043",
    desc: "Scoped account reads and allowlisted reversible updates. Can read balance, due date, status. Can update phone/address with step-up auth.",
    contract: {
      allowed_inputs: ["authenticated account ref", "requested field"],
      writable_state: ["fresh result", "servicing proposal"],
      tool_authority: ["read", "execution (reversible only)"],
      required_exits: ["fresh_result", "precondition_rejected", "handoff"],
    },
    tools: ["get_account_overview", "get_payment_methods", "update_phone_number"],
  },
  {
    id: "arrangement", label: "Arrangement", type: "subgraph", x: 440, y: 370, r: 30, color: "#d29922",
    desc: "Quote and validation only — no side effects. Computes payoff quotes, validates payment proposals, checks eligibility. Cannot execute payments.",
    contract: {
      allowed_inputs: ["balance snapshot", "customer proposal"],
      writable_state: ["normalized amount/date/plan"],
      tool_authority: ["proposal only (no side effects)"],
      required_exits: ["validated_proposal", "invalid_proposal"],
    },
    tools: ["calculate_payoff_quote", "validate_payment_proposal"],
  },
  {
    id: "sensitive_action", label: "Sensitive\nAction", type: "subgraph", x: 600, y: 370, r: 30, color: "#da3633",
    desc: "Most security-critical subgraph. Owns protected collection (credentials bypass LLM), explicit authorization (versioned artifact), and transaction execution. HIDDEN from chat channel.",
    contract: {
      allowed_inputs: ["validated proposal", "auth level", "auth version"],
      writable_state: ["action lifecycle", "opaque token"],
      tool_authority: ["execution (protected + execute)"],
      required_exits: ["confirmed", "rejected", "cancelled", "unknown_reconciling"],
    },
    tools: ["schedule_payment", "update_phone_number"],
  },
  {
    id: "compliance", label: "Compliance\nHandoff", type: "subgraph", x: 760, y: 370, r: 30, color: "#8957e5",
    desc: "Handles compliance-sensitive situations (bankruptcy, attorney, death, dispute) and human transfers. May preempt every other subgraph.",
    contract: {
      allowed_inputs: ["current action", "channel", "policy context"],
      writable_state: ["policy decision", "transfer request"],
      tool_authority: ["execution (transfer only)"],
      required_exits: ["policy_allow", "policy_deny", "transfer_accepted"],
    },
    tools: ["transfer_to_agent"],
  },
  {
    id: "gate", label: "Completion\nGate", type: "gate", x: 400, y: 500, r: 26, color: "#1f6feb",
    desc: "Final deterministic check. Validates exit state against subgraph contract. Enforces success-language rules: CONFIRMED required before success phrasing. UNKNOWN → 'pending' only.",
    rules: [
      "sensitive_action + CONFIRMED → success language allowed",
      "sensitive_action + UNKNOWN → 'pending' only",
      "sensitive_action + REJECTED → failure language only",
      "Invalid exit state → force handoff",
    ],
  },
  {
    id: "END", label: "END", type: "control", x: 400, y: 580, r: 18, color: "#6e7681",
    desc: "Turn complete. State persisted to database. Reply filtered through output filter and sent to customer.",
  },
];

export const EDGES: GraphEdge[] = [
  { from: "START", to: "preconditions" },
  { from: "preconditions", to: "loop_budget", label: "pass" },
  { from: "preconditions", to: "END", label: "fail", dashed: true },
  { from: "loop_budget", to: "router" },
  { from: "router", to: "knowledge", label: "knowledge" },
  { from: "router", to: "account_servicing", label: "account" },
  { from: "router", to: "arrangement", label: "arrangement" },
  { from: "router", to: "sensitive_action", label: "sensitive" },
  { from: "router", to: "compliance", label: "compliance" },
  { from: "knowledge", to: "gate" },
  { from: "account_servicing", to: "gate" },
  { from: "arrangement", to: "gate" },
  { from: "sensitive_action", to: "gate" },
  { from: "compliance", to: "gate" },
  { from: "gate", to: "END" },
];

export const IMPLEMENTATION: ImplItem[] = [
  { component: "LangGraph Universal Graph", status: "operational", detail: "5 subgraphs, intent router, completion gate — compiles and runs end-to-end" },
  { component: "Tool Envelope Contract", status: "operational", detail: "Server-derived identity (model cannot supply customer_id or auth_level)" },
  { component: "Tool Registry (Capability-Based Exposure)", status: "operational", detail: "Execution tools hidden from model until preconditions met" },
  { component: "Sensitive Action State Machine", status: "operational", detail: "PROPOSED → CONFIRMED / UNKNOWN / REJECTED with idempotency keys" },
  { component: "Versioned Authorization Artifacts", status: "operational", detail: "Binds actor + amount + date + method; invalidates on any field change" },
  { component: "Intent Router", status: "operational", detail: "Deterministic with channel + auth constraint validation, compliance preemption" },
  { component: "Evidence Completion Gate", status: "operational", detail: "Success language blocked until CONFIRMED persisted; UNKNOWN → 'pending' only" },
  { component: "Compliance Engine", status: "operational", detail: "Stateless, strictest-wins, fail-closed: daily caps, scheduling window, opt-outs, state exclusions — enforced at the execution boundary" },
  { component: "Temporal Durable Workflows", status: "operational", detail: "Payment arrangement (durable timer to scheduled date) + UNKNOWN reconciliation with durable backoff; tested against Temporal's time-skipping env" },
  { component: "Web Chat Channel", status: "operational", detail: "FastAPI session + message API wired to the agent runtime; payment execution blocked on chat; /chat demo widget" },
  { component: "Output Filter", status: "operational", detail: "Word-boundary, case-preserving, streaming-safe (loan → contract)" },
  { component: "Mock FAC API", status: "running", detail: "3 fake accounts (Westpond, CPR tenants) with payment methods and negotiation rules" },
  { component: "Mock Payment Provider", status: "running", detail: "Deterministic by action_id, simulates timeouts for UNKNOWN state testing" },
  { component: "LLM Integration (OpenAI)", status: "wired", detail: "Reasoning engine, route-specific prompts, tool calling — needs API credits" },
  { component: "Database Persistence", status: "wired", detail: "SQLAlchemy async: tool_actions, authorization_artifacts, sessions, audit_events" },
  { component: "Interactive CLI", status: "operational", detail: "Real conversations through the safety system (deterministic + LLM modes)" },
  { component: "Test Suite", status: "operational", detail: "236 passed, 5 skipped; graph, policy, workflow, chat, and eval coverage" },
  { component: "Agent Graph Visualizer", status: "operational", detail: "This React/TypeScript UI you're looking at right now" },
];

export const ROADMAP: MilestoneItem[] = [
  {
    name: "M1 — Core Agent + Tools + State", status: "done",
    desc: "The foundation: graph topology, tool architecture, state management, safety boundaries.",
    items: [
      "LangGraph with 5 capability-scoped subgraphs",
      "Tool envelope with server-derived identity",
      "Capability-based tool exposure (execution hidden until authorized)",
      "8-state action state machine (PROPOSED → CONFIRMED / UNKNOWN)",
      "Versioned authorization artifacts",
      "Intent router with channel + auth constraints",
      "Evidence completion gate",
      "Mock FAC API + mock payment provider",
      "236 passed, 5 skipped across the full suite",
    ],
  },
  {
    name: "M2 — Compliance Engine + Temporal", status: "done",
    desc: "Stateless compliance engine and durable orchestration for multi-day workflows.",
    items: [
      "Stateless compliance engine (strictest-wins, fail-closed)",
      "Rule registry: time windows, caps, DNC, opt-outs, state exclusions",
      "Temporal workflow per account (durable timers)",
      "Reconciliation worker for UNKNOWN state",
      "⬜ Cross-channel arbitration via journey version",
      "⬜ Replay tests on deploy",
    ],
  },
  {
    name: "M3 — SMS Channel", status: "planned",
    desc: "Real SMS via Twilio with coalescing, compliance keywords, and outbound approval pipeline.",
    items: [
      "Twilio webhook handler (inbound + delivery receipts)",
      "Inbound coalescing (2.5s quiet window)",
      "Deterministic pre-model path for STOP/opt-out",
      "Outbound pipeline: plan → approval → compliance → send",
      "Event ID deduplication",
    ],
  },
  {
    name: "M4 — Web Chat", status: "in-progress",
    desc: "Core web chat is implemented; browser JWT auth, durable sessions, and post-call processing remain.",
    items: [
      "✅ Local /chat demo widget",
      "✅ FastAPI session, message, and history API",
      "✅ Bounded in-process session isolation",
      "✅ Narrow tool surface (no payment execution)",
      "✅ $0.00 anti-pattern prevention",
      "⬜ Browser JWT auth",
      "⬜ Durable session store and reconnect handling",
      "⬜ Post-call processing + analytics",
    ],
  },
  {
    name: "M5 — Voice Channel", status: "planned",
    desc: "LiveKit-based voice with ASR/TTS, DTMF protected collection, and interruption handling.",
    items: [
      "LiveKit server (self-hosted)",
      "ASR + TTS pipeline",
      "VAD + endpointing",
      "DTMF protected collection (credentials bypass LLM)",
      "Interruption handling (cancel in-flight model)",
      "Disconnect-during-execution recovery",
    ],
  },
  {
    name: "M6 — Observability + Evals", status: "in-progress",
    desc: "Deterministic evaluation runner and privacy-aware turn traces are implemented; production dashboards and broader model-quality evals remain.",
    items: [
      "✅ Deterministic JSON evaluation runner",
      "✅ Routing, channel, auth, compliance, gate, and output cases",
      "✅ Privacy-aware turn trace lifecycle",
      "✅ Optional JSONL trace sink and OpenTelemetry span API",
      "⬜ OTLP exporter configuration and dashboards",
      "⬜ Broader model-quality and groundedness evals",
      "⬜ Evidence bundles on deploy",
    ],
  },
];

// ── Router simulation (mirrors Python router) ───────────────────────────────

const COMPLIANCE_PHRASES = ["death","deceased","bankruptcy","bankrupt","attorney","lawyer","dispute","cease"];
const CHANNEL_ROUTES: Record<string, string[]> = {
  sms: ["knowledge","account_servicing","arrangement","sensitive_action","compliance_handoff"],
  chat: ["knowledge","account_servicing","arrangement","compliance_handoff"],
  voice: ["knowledge","account_servicing","arrangement","sensitive_action","compliance_handoff"],
};
const AUTH_LEVELS = ["anonymous","verified","step_up"];
const AUTH_REQS: Record<string, string> = {
  knowledge: "anonymous", account_servicing: "verified",
  arrangement: "verified", sensitive_action: "step_up", compliance_handoff: "anonymous",
};

const INTENT_PATTERNS: { regex: RegExp; route: string }[] = [
  { regex: /\b(death|deceased|bankruptcy|bankrupt|attorney|lawyer|dispute|cease)\b/i, route: "compliance_handoff" },
  { regex: /\b(human|agent|representative|talk to someone|manager)\b/i, route: "compliance_handoff" },
  { regex: /\b(settle|settlement|payment plan|installment|payoff|pay off)\b/i, route: "arrangement" },
  { regex: /\b(update|change|new phone|new address|balance|due date|how much do i owe|how much is my)\b/i, route: "account_servicing" },
  { regex: /^(how|what|why|when|where|can i|do you|is|are)\b/i, route: "knowledge" },
  { regex: /\b(pay|payment|charge|card|bank account)\b/i, route: "sensitive_action" },
  { regex: /\b(how|what|why|when|where|can i|do you|policy|faq|question)\b/i, route: "knowledge" },
];

const ROUTE_TO_NODE: Record<string, string> = {
  knowledge: "knowledge", account_servicing: "account_servicing",
  arrangement: "arrangement", sensitive_action: "sensitive_action",
  compliance_handoff: "compliance",
};

export function simulateRoute(utterance: string, channel: string, authLevel: string) {
  const lower = utterance.toLowerCase();
  for (const phrase of COMPLIANCE_PHRASES) {
    if (lower.includes(phrase)) {
      return {
        route: "compliance_handoff",
        reason: `Compliance phrase detected: "${phrase}" — preempting all other routing`,
        preempted: true, blocked: false,
        path: ["START","preconditions","loop_budget","router","compliance","gate","END"],
      };
    }
  }
  let proposed = "knowledge";
  for (const { regex, route } of INTENT_PATTERNS) {
    if (regex.test(utterance)) { proposed = route; break; }
  }
  const allowed = CHANNEL_ROUTES[channel] || [];
  if (!allowed.includes(proposed)) {
    return {
      route: "knowledge",
      reason: `"${proposed}" is not allowed on ${channel} channel → falling back to knowledge`,
      preempted: false, blocked: true,
      path: ["START","preconditions","loop_budget","router","knowledge","gate","END"],
    };
  }
  const required = AUTH_REQS[proposed] || "verified";
  if (AUTH_LEVELS.indexOf(authLevel) < AUTH_LEVELS.indexOf(required)) {
    return {
      route: "knowledge",
      reason: `"${proposed}" requires ${required} auth, you have ${authLevel} → falling back to knowledge`,
      preempted: false, blocked: true,
      path: ["START","preconditions","loop_budget","router","knowledge","gate","END"],
    };
  }
  const targetNode = ROUTE_TO_NODE[proposed] || "knowledge";
  return {
    route: proposed,
    reason: `Routed normally via pattern matching`,
    preempted: false, blocked: false,
    path: ["START","preconditions","loop_budget","router",targetNode,"gate","END"],
  };
}
