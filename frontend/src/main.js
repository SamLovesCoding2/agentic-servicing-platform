// Salient Replica — Agent Graph Visualizer
// Interactive canvas-based visualization of the Taylor agent graph topology.
// Click nodes to inspect contracts, tools, and routing rules.
// Use the simulator to test how utterances route through the graph.

// ── Graph Definition ─────────────────────────────────────────────────────────

const GRAPH_NODES = [
    // Control flow
    { id: "START", label: "START", type: "control", x: 400, y: 40, r: 20, color: "#8957e5",
      desc: "Entry point for every conversation turn." },
    { id: "preconditions", label: "Preconditions", type: "control", x: 400, y: 110, r: 22, color: "#8957e5",
      desc: "Validates conversation_id, customer_id, channel, and turn budget. If any are missing, routes to safe handoff." },
    { id: "loop_budget", label: "Loop Budget", type: "control", x: 400, y: 180, r: 22, color: "#8957e5",
      desc: "Checks max_model_turns (10), max_tool_attempts (5), and max_elapsed_seconds (30). Rejects if exceeded." },
    { id: "router", label: "Intent Router", type: "control", x: 400, y: 260, r: 26, color: "#8957e5",
      desc: "Deterministic entry with classifier assistance. Checks compliance phrases first (preempt), then classifies intent, validates route against channel + auth constraints. Falls back to knowledge if invalid.",
      rules: [
          "Compliance phrases (bankruptcy, attorney, death, dispute) → preempt to compliance_handoff",
          "Chat channel cannot route to sensitive_action (architectural constraint)",
          "Sensitive action requires step_up auth",
          "Account servicing requires verified auth",
          "Knowledge is the safe default fallback"
      ]
    },
    // Subgraphs
    { id: "knowledge", label: "Knowledge\nSubgraph", type: "subgraph", x: 120, y: 380, r: 34, color: "#1a7f37",
      contract: {
          allowed_inputs: ["sanitized question", "locale"],
          writable_state: ["answer draft", "citations"],
          tool_authority: ["read-only retrieval"],
          required_exits: ["cited_answer", "no_answer"]
      },
      tools: ["search_faq"],
      desc: "Read-only retrieval. Answers FAQs and policy questions with citations. Cannot write any state except an answer draft." },
    { id: "account_servicing", label: "Account\nServicing", type: "subgraph", x: 280, y: 380, r: 34, color: "#1a7f37",
      contract: {
          allowed_inputs: ["authenticated account ref", "requested field"],
          writable_state: ["fresh result", "servicing proposal"],
          tool_authority: ["read", "execution (reversible only)"],
          required_exits: ["fresh_result", "precondition_rejected", "handoff"]
      },
      tools: ["get_account_overview", "get_payment_methods", "update_phone_number"],
      desc: "Scoped account reads and allowlisted reversible updates. Can read balance, due date, status. Can update phone/address with step-up auth." },
    { id: "arrangement", label: "Arrangement\nSubgraph", type: "subgraph", x: 440, y: 380, r: 34, color: "#fb8500",
      contract: {
          allowed_inputs: ["balance snapshot", "customer proposal (amount, date, method)"],
          writable_state: ["normalized amount/date/plan candidates"],
          tool_authority: ["proposal only (no side effects)"],
          required_exits: ["validated_proposal", "invalid_proposal"]
      },
      tools: ["calculate_payoff_quote", "validate_payment_proposal"],
      desc: "Quote and validation only — no side effects. Computes payoff quotes, validates payment proposals, checks eligibility. Cannot execute payments." },
    { id: "sensitive_action", label: "Sensitive\nAction", type: "subgraph", x: 600, y: 380, r: 34, color: "#cf222e",
      contract: {
          allowed_inputs: ["validated proposal", "auth level", "authorization version"],
          writable_state: ["action lifecycle", "opaque token reference"],
          tool_authority: ["execution (protected collection + execute)"],
          required_exits: ["confirmed", "rejected", "cancelled", "unknown_reconciling"]
      },
      tools: ["schedule_payment", "update_phone_number"],
      desc: "Most security-critical subgraph. Owns protected collection (credentials bypass LLM), explicit authorization (versioned artifact), and transaction execution. HIDDEN from chat channel." },
    { id: "compliance", label: "Compliance\nHandoff", type: "subgraph", x: 760, y: 380, r: 34, color: "#8957e5",
      contract: {
          allowed_inputs: ["current action", "channel", "policy context"],
          writable_state: ["policy decision", "transfer request"],
          tool_authority: ["execution (transfer only)"],
          required_exits: ["policy_allow", "policy_deny", "transfer_accepted"]
      },
      tools: ["transfer_to_agent"],
      desc: "Handles compliance-sensitive situations (bankruptcy, attorney, death, dispute) and human transfers. May preempt every other subgraph." },
    // Completion gate
    { id: "gate", label: "Completion\nGate", type: "gate", x: 400, y: 510, r: 28, color: "#1f6feb",
      desc: "Final deterministic check. Validates exit state against subgraph contract. Enforces success-language rules: CONFIRMED required before success phrasing. UNKNOWN → 'pending' only. If gate fails, forces handoff.",
      rules: [
          "sensitive_action + CONFIRMED → success language allowed",
          "sensitive_action + UNKNOWN → 'pending' only (no success/failure)",
          "sensitive_action + REJECTED → failure language only",
          "Invalid exit state → force handoff",
          "knowledge + no_answer → no success language"
      ]
    },
    { id: "END", label: "END", type: "control", x: 400, y: 590, r: 20, color: "#8957e5",
      desc: "Turn complete. State persisted to database. Reply filtered through output filter and sent to customer." },
];

const GRAPH_EDGES = [
    { from: "START", to: "preconditions" },
    { from: "preconditions", to: "loop_budget", label: "pass" },
    { from: "preconditions", to: "END", label: "fail → handoff", dashed: true },
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

// ── Router Simulation (mirrors taylor/graphs/universal/router.py) ────────────

const COMPLIANCE_PHRASES = ["death","deceased","bankruptcy","bankrupt","attorney","lawyer","dispute","cease"];
const CHANNEL_ROUTES = {
    sms: ["knowledge","account_servicing","arrangement","sensitive_action","compliance_handoff"],
    chat: ["knowledge","account_servicing","arrangement","compliance_handoff"],
    voice: ["knowledge","account_servicing","arrangement","sensitive_action","compliance_handoff"],
};
const AUTH_LEVELS = ["anonymous","verified","step_up"];
const AUTH_REQS = {
    knowledge: "anonymous", account_servicing: "verified",
    arrangement: "verified", sensitive_action: "step_up", compliance_handoff: "anonymous",
};

const INTENT_PATTERNS = [
    { regex: /\b(death|deceased|bankruptcy|bankrupt|attorney|lawyer|dispute|cease)\b/i, route: "compliance_handoff" },
    { regex: /\b(human|agent|representative|talk to someone|manager)\b/i, route: "compliance_handoff" },
    { regex: /\b(settle|settlement|payment plan|installment|payoff|pay off)\b/i, route: "arrangement" },
    { regex: /\b(update|change|new phone|new address|balance|due date|how much do i owe|how much is my)\b/i, route: "account_servicing" },
    { regex: /^(how|what|why|when|where|can i|do you|is|are)\b/i, route: "knowledge" },
    { regex: /\b(pay|payment|charge|card|bank account)\b/i, route: "sensitive_action" },
    { regex: /\b(how|what|why|when|where|can i|do you|policy|faq|question)\b/i, route: "knowledge" },
];

function simulateRoute(utterance, channel, authLevel) {
    // Compliance preempt
    const lower = utterance.toLowerCase();
    for (const phrase of COMPLIANCE_PHRASES) {
        if (lower.includes(phrase)) {
            return { route: "compliance_handoff", reason: `Compliance phrase detected: "${phrase}"`, preempted: true };
        }
    }
    // Classify
    let proposed = "knowledge";
    for (const { regex, route } of INTENT_PATTERNS) {
        if (regex.test(utterance)) { proposed = route; break; }
    }
    // Validate channel
    const allowed = CHANNEL_ROUTES[channel] || [];
    if (!allowed.includes(proposed)) {
        return { route: "knowledge", reason: `"${proposed}" not allowed on ${channel} channel → fallback to knowledge`, blocked: true };
    }
    // Validate auth
    const required = AUTH_REQS[proposed] || "verified";
    if (AUTH_LEVELS.indexOf(authLevel) < AUTH_LEVELS.indexOf(required)) {
        return { route: "knowledge", reason: `"${proposed}" requires ${required} auth, you have ${authLevel} → fallback to knowledge`, blocked: true };
    }
    return { route: proposed, reason: `Routed normally`, blocked: false };
}

// ── Canvas Renderer ──────────────────────────────────────────────────────────

const canvas = document.getElementById("canvas");
const ctx = canvas.getContext("2d");
let scale = 1, offsetX = 0, offsetY = 0;
let selectedNode = null;
let highlightedRoute = null;

function resizeCanvas() {
    canvas.width = window.innerWidth - 380;
    canvas.height = window.innerHeight;
}
resizeCanvas();
window.addEventListener("resize", resizeCanvas);

function getNode(id) { return GRAPH_NODES.find(n => n.id === id); }

function drawEdge(edge) {
    const from = getNode(edge.from);
    const to = getNode(edge.to);
    if (!from || !to) return;

    const dx = to.x - from.x;
    const dy = to.y - from.y;
    const dist = Math.sqrt(dx * dx + dy * dy);
    const ux = dx / dist, uy = dy / dist;

    const x1 = from.x + ux * from.r;
    const y1 = from.y + uy * from.r;
    const x2 = to.x - ux * to.r;
    const y2 = to.y - uy * to.r;

    // Check if this edge is highlighted
    const isHighlighted = highlightedRoute && highlightedRoute.path.includes(edge.from) && highlightedRoute.path.includes(edge.to);

    ctx.save();
    ctx.strokeStyle = isHighlighted ? "#58a6ff" : (edge.dashed ? "#484f58" : "#30363d");
    ctx.lineWidth = isHighlighted ? 3 : 1.5;
    ctx.setLineDash(edge.dashed ? [5, 5] : []);

    ctx.beginPath();
    // Curve slightly for routing edges
    if (edge.label && from.id === "router") {
        const mx = (x1 + x2) / 2;
        const my = (y1 + y2) / 2 - 10;
        ctx.moveTo(x1, y1);
        ctx.quadraticCurveTo(mx, my, x2, y2);
    } else {
        ctx.moveTo(x1, y1);
        ctx.lineTo(x2, y2);
    }
    ctx.stroke();
    ctx.setLineDash([]);

    // Arrowhead
    const angle = Math.atan2(y2 - y1, x2 - x1);
    ctx.fillStyle = isHighlighted ? "#58a6ff" : (edge.dashed ? "#484f58" : "#30363d");
    ctx.beginPath();
    ctx.moveTo(x2, y2);
    ctx.lineTo(x2 - 8 * Math.cos(angle - 0.3), y2 - 8 * Math.sin(angle - 0.3));
    ctx.lineTo(x2 - 8 * Math.cos(angle + 0.3), y2 - 8 * Math.sin(angle + 0.3));
    ctx.closePath();
    ctx.fill();

    // Label
    if (edge.label) {
        const lx = (x1 + x2) / 2;
        const ly = (y1 + y2) / 2 - 5;
        ctx.fillStyle = isHighlighted ? "#58a6ff" : "#6e7681";
        ctx.font = "10px sans-serif";
        ctx.textAlign = "center";
        ctx.fillText(edge.label, lx, ly);
    }
    ctx.restore();
}

function drawNode(node) {
    ctx.save();

    // Check if highlighted
    const isHighlighted = highlightedRoute && highlightedRoute.path.includes(node.id);
    const isSelected = selectedNode && selectedNode.id === node.id;

    // Glow for highlighted
    if (isHighlighted) {
        ctx.shadowColor = node.color;
        ctx.shadowBlur = 20;
    }

    // Circle
    ctx.fillStyle = node.color + (isHighlighted || isSelected ? "" : "88");
    ctx.strokeStyle = node.color;
    ctx.lineWidth = isSelected ? 3 : 2;
    ctx.beginPath();
    ctx.arc(node.x, node.y, node.r, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    ctx.shadowBlur = 0;

    // Label
    ctx.fillStyle = "#fff";
    ctx.font = "bold 11px sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    const lines = node.label.split("\n");
    lines.forEach((line, i) => {
        ctx.fillText(line, node.x, node.y - (lines.length - 1) * 6 + i * 12);
    });

    ctx.restore();
}

function draw() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.save();
    ctx.translate(offsetX, offsetY);
    ctx.scale(scale, scale);

    // Edges first
    GRAPH_EDGES.forEach(drawEdge);
    // Nodes on top
    GRAPH_NODES.forEach(drawNode);

    ctx.restore();
}

// ── Interaction ──────────────────────────────────────────────────────────────

let isDragging = false, lastX = 0, lastY = 0;

canvas.addEventListener("mousedown", (e) => {
    const node = getNodeAt(e.clientX, e.clientY);
    if (node) {
        selectedNode = node;
        showNodeInfo(node);
        draw();
    } else {
        isDragging = true;
        lastX = e.clientX;
        lastY = e.clientY;
    }
});

canvas.addEventListener("mousemove", (e) => {
    if (isDragging) {
        offsetX += e.clientX - lastX;
        offsetY += e.clientY - lastY;
        lastX = e.clientX;
        lastY = e.clientY;
        draw();
    }
});

canvas.addEventListener("mouseup", () => { isDragging = false; });

canvas.addEventListener("wheel", (e) => {
    e.preventDefault();
    const delta = e.deltaY > 0 ? 0.9 : 1.1;
    scale *= delta;
    scale = Math.max(0.3, Math.min(3, scale));
    draw();
});

function getNodeAt(mx, my) {
    const x = (mx - offsetX) / scale;
    const y = (my - offsetY) / scale;
    for (const node of GRAPH_NODES) {
        const dx = x - node.x;
        const dy = y - node.y;
        if (dx * dx + dy * dy <= node.r * node.r) return node;
    }
    return null;
}

function showNodeInfo(node) {
    const sidebar = document.getElementById("node-info");
    let html = `<div class="node-info">
        <div class="label">Node</div>
        <div class="value">${node.label.replace(/\n/g, " ")}</div>
        <div class="label">Description</div>
        <div class="value">${node.desc}</div>`;

    if (node.contract) {
        html += `<div class="label">Contract — Allowed Inputs</div><div class="value">${node.contract.allowed_inputs.join(", ")}</div>`;
        html += `<div class="label">Contract — Writable State</div><div class="value">${node.contract.writable_state.join(", ")}</div>`;
        html += `<div class="label">Contract — Tool Authority</div><div class="value">${node.contract.tool_authority.join(", ")}</div>`;
        html += `<div class="label">Contract — Required Exits</div><div class="value">${node.contract.required_exits.join(", ")}</div>`;
    }

    if (node.tools) {
        html += `<div class="label">Tools</div><div class="value"><ul class="tool-list">`;
        node.tools.forEach(t => {
            let badge = "";
            if (t === "search_faq" || t === "get_account_overview" || t === "get_payment_methods") badge = '<span class="badge badge-read">read</span>';
            else if (t === "calculate_payoff_quote" || t === "validate_payment_proposal") badge = '<span class="badge badge-proposal">proposal</span>';
            else badge = '<span class="badge badge-execution">execution</span>';
            html += `<li>${badge} ${t}</li>`;
        });
        html += `</ul></div>`;
    }

    if (node.rules) {
        html += `<div class="label">Rules</div><div class="value"><ul class="tool-list">`;
        node.rules.forEach(r => html += `<li>• ${r}</li>`);
        html += `</ul></div>`;
    }

    html += `</div>`;
    sidebar.innerHTML = html;
}

// ── Zoom Controls ────────────────────────────────────────────────────────────

document.getElementById("zoom-in").addEventListener("click", () => { scale *= 1.2; draw(); });
document.getElementById("zoom-out").addEventListener("click", () => { scale *= 0.83; draw(); });
document.getElementById("reset").addEventListener("click", () => {
    scale = 1; offsetX = 0; offsetY = 0;
    highlightedRoute = null;
    document.getElementById("result").style.display = "none";
    draw();
});

// ── Simulator ────────────────────────────────────────────────────────────────

document.getElementById("simulate").addEventListener("click", () => {
    const utterance = document.getElementById("utterance").value;
    const channel = document.getElementById("channel").value;
    const auth = document.getElementById("auth").value;

    const result = simulateRoute(utterance, channel, auth);

    // Build highlighted path
    const routeMap = {
        knowledge: "knowledge", account_servicing: "account_servicing",
        arrangement: "arrangement", sensitive_action: "sensitive_action",
        compliance_handoff: "compliance"
    };
    const targetNode = routeMap[result.route] || "knowledge";

    highlightedRoute = {
        path: ["START", "preconditions", "loop_budget", "router", targetNode, "gate", "END"]
    };

    // Show result
    const resultDiv = document.getElementById("result");
    resultDiv.style.display = "block";
    const reasonClass = result.blocked ? "blocked" : (result.preempted ? "blocked" : "exit");
    resultDiv.innerHTML = `
        <div class="label">Utterance</div>
        <div class="value">"${utterance}"</div>
        <div class="label">Channel / Auth</div>
        <div class="value">${channel} / ${auth}</div>
        <div class="route">→ Route: ${result.route}</div>
        <div class="${reasonClass}">${result.reason}</div>
    `;

    draw();
});

// ── Initial Render ───────────────────────────────────────────────────────────
draw();
