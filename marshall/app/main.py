"""
Marshall — FastAPI backend for the Salient Replica.

M4 core: the web chat channel. Exposes a session + message API wired to
the Taylor agent runtime (deterministic mode by default; LLM automatically
when OPENAI_API_KEY is present and MARSHALL_LLM_ENABLED isn't "0").

Channel-safety invariants:
  - Chat cannot route to `sensitive_action` (payment execution blocked by
    the router AND the channel tool override).
  - Identity (customer_id, auth_level) is server-derived at session creation.
  - Every turn still passes the completion gate + output filter.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from marshall.app.sessions import chat_sessions
from taylor.graphs.universal.state import Channel
from taylor.runtime.text_runtime import TextRuntime

logger = logging.getLogger(__name__)

app = FastAPI(title="Marshall", version="0.2.0", description="Salient Replica backend")


def create_runtime() -> TextRuntime:
    """Build the shared agent runtime. LLM is enabled automatically when an
    API key is available unless explicitly disabled (MARSHALL_LLM_ENABLED=0)."""
    llm_enabled = os.environ.get("MARSHALL_LLM_ENABLED", "auto").lower()
    force_deterministic = llm_enabled in ("0", "false", "off")
    if force_deterministic:
        logger.info("Marshall chat runtime: deterministic mode (no LLM)")
    return TextRuntime(config_name="default_en", force_deterministic=force_deterministic)


_RUNTIME: TextRuntime | None = None


def runtime() -> TextRuntime:
    """App-scoped runtime singleton."""
    global _RUNTIME
    if _RUNTIME is None:
        _RUNTIME = create_runtime()
    return _RUNTIME


# ── Request/response models ───────────────────────────────────────────────────

class CreateSessionRequest(BaseModel):
    customer_id: str = Field(default="cust_demo_001", description="Demo customer tag; server assigns auth.")
    auth_level: str = Field(
        default="verified",
        description="Server-assigned auth level (anonymous | verified). Chat cannot do step_up.",
    )


class MessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class MessageResponse(BaseModel):
    reply: str
    route: str
    exit_state: str
    gate_passed: bool
    success_language_allowed: bool
    action_status: str | None = None


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy", "service": "marshall", "version": "0.2.0"}


@app.get("/ready")
async def ready() -> dict[str, str]:
    return {"status": "ready", "service": "marshall"}


# ── Chat channel ──────────────────────────────────────────────────────────────

@app.post("/api/chat/sessions")
async def create_chat_session(body: CreateSessionRequest) -> dict[str, Any]:
    """Create a chat session. The server derives identity; the client gets an
    opaque session_id it must present on every message."""
    if body.auth_level not in ("anonymous", "verified"):
        raise HTTPException(status_code=400, detail="auth_level must be anonymous or verified")
    session = chat_sessions.create(customer_id=body.customer_id, auth_level=body.auth_level)
    logger.info(
        "Chat session created: %s customer=%s auth=%s",
        session.session_id, session.customer_id, session.auth_level.value,
    )
    return {
        "session_id": session.session_id,
        "conversation_id": session.conversation_id,
        "customer_id": session.customer_id,
        "auth_level": session.auth_level.value,
    }


@app.post("/api/chat/sessions/{session_id}/messages")
async def send_chat_message(session_id: str, body: MessageRequest) -> MessageResponse:
    """Run one turn for an existing chat session."""
    session = chat_sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")

    result = await runtime().run_turn(
        utterance=body.message,
        conversation_id=session.conversation_id,
        customer_id=session.customer_id,
        auth_level=session.auth_level,
        channel=Channel.CHAT,
    )

    chat_sessions.append_message(session_id, "user", body.message)
    chat_sessions.append_message(session_id, "assistant", result["reply"])

    gate = result.get("gate_result") or {}
    return MessageResponse(
        reply=result["reply"],
        route=str(result["route"]),
        exit_state=str(result["exit_state"]),
        gate_passed=bool(gate.get("gate_passed", False)),
        success_language_allowed=bool(result.get("success_language_allowed", False)),
        action_status=result.get("action_status"),
    )


@app.get("/api/chat/sessions/{session_id}/messages")
async def get_chat_history(session_id: str) -> dict[str, Any]:
    """Return the bounded transcript for a session."""
    session = chat_sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return {"session_id": session_id, "messages": session.messages}


# ── Minimal widget (local demo only) ─────────────────────────────────────────

CHAT_WIDGET_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Taylor — Web Chat</title>
<style>
  body { font-family: -apple-system, system-ui, sans-serif; background: #0d1117; color: #e6edf3; margin: 0; }
  main { max-width: 720px; margin: 0 auto; padding: 24px; }
  h1 { font-size: 20px; color: #c9d1d9; }
  #log { border: 1px solid #30363d; border-radius: 8px; padding: 12px; height: 420px; overflow-y: auto; background: #161b22; }
  .msg { margin: 8px 0; padding: 8px 10px; border-radius: 8px; max-width: 80%; white-space: pre-wrap; }
  .user { background: #1f6feb; color: #fff; margin-left: auto; }
  .agent { background: #21262d; border: 1px solid #30363d; }
  .meta { font-size: 11px; color: #8b949e; margin-top: 4px; }
  form { display: flex; gap: 8px; margin-top: 12px; }
  input { flex: 1; padding: 10px; border-radius: 8px; border: 1px solid #30363d; background: #0d1117; color: #e6edf3; }
  button { padding: 10px 16px; border: 0; border-radius: 8px; background: #1f6feb; color: #fff; cursor: pointer; }
</style>
</head>
<body>
<main>
  <h1>Taylor — Salient Replica (web chat demo)</h1>
  <div id="log"></div>
  <form id="form">
    <input id="input" placeholder="Type a message…" autocomplete="off">
    <button type="submit">Send</button>
  </form>
</main>
<script>
  let sessionId = null;
  const logEl = document.getElementById('log');
  const addMsg = (role, text, meta='') => {
    const d = document.createElement('div');
    d.className = 'msg ' + (role === 'user' ? 'user' : 'agent');
    d.textContent = text;
    if (meta) { const m = document.createElement('div'); m.className = 'meta'; m.textContent = meta; d.appendChild(m); }
    logEl.appendChild(d); logEl.scrollTop = logEl.scrollHeight;
  };
  async function init() {
    const res = await fetch('/api/chat/sessions', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({customer_id: 'cust_demo_001', auth_level: 'verified'})
    });
    const data = await res.json();
    sessionId = data.session_id;
    addMsg('agent', 'Hi! I can help with your FAC account. This demo uses the deterministic mode, so no LLM credits are consumed.');
  }
  document.getElementById('form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const input = document.getElementById('input');
    const text = input.value.trim();
    if (!text || !sessionId) return;
    input.value = '';
    addMsg('user', text);
    const res = await fetch(`/api/chat/sessions/${sessionId}/messages`, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({message: text})
    });
    const data = await res.json();
    if (!res.ok) { addMsg('agent', 'Error: ' + (data.detail || res.status)); return; }
    addMsg('agent', data.reply, `route: ${data.route} · exit: ${data.exit_state} · gate: ${data.gate_passed}`);
  });
  init();
</script>
</body>
</html>"""


@app.get("/chat", response_class=HTMLResponse)
async def chat_widget() -> str:
    """Tiny self-contained chat widget for local demos."""
    return CHAT_WIDGET_HTML
