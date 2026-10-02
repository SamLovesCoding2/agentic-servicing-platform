"""
Marshall — FastAPI backend for the Agentic Servicing Platform.

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

import base64
import logging
import os
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from marshall.app.auth import (
    enforce_session_access,
    issue_token,
    resolve_identity,
)
from marshall.app.sessions import chat_sessions
from marshall.app.voice_provider import (
    ElevenLabsVoiceProvider,
    VoiceProvider,
    VoiceProviderError,
    decode_audio_base64,
)
from marshall.app.voice_sessions import voice_sessions
from taylor.graphs.universal.state import Channel
from taylor.runtime.text_runtime import TextRuntime

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Marshall",
    version="0.2.0",
    description="Agentic Servicing Platform backend",
)


def create_voice_provider() -> VoiceProvider:
    """Create the configured voice adapter without requiring paid credentials."""
    return ElevenLabsVoiceProvider()


_VOICE_PROVIDER: VoiceProvider | None = None


def voice_provider() -> VoiceProvider:
    global _VOICE_PROVIDER
    if _VOICE_PROVIDER is None:
        _VOICE_PROVIDER = create_voice_provider()
    return _VOICE_PROVIDER


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
    tenant_id: str = Field(default="demo", min_length=1, max_length=100)


class DemoTokenRequest(BaseModel):
    customer_id: str = Field(default="cust_demo_001", min_length=1, max_length=255)
    tenant_id: str = Field(default="demo", min_length=1, max_length=100)
    auth_level: str = Field(default="verified")


class MessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class MessageResponse(BaseModel):
    reply: str
    route: str
    exit_state: str
    gate_passed: bool
    success_language_allowed: bool
    action_status: str | None = None


class CreateVoiceSessionRequest(BaseModel):
    customer_id: str = Field(default="cust_demo_001", description="Demo customer tag.")
    auth_level: str = Field(
        default="verified",
        description="Server-assigned auth level (anonymous | verified | step_up).",
    )
    tenant_id: str = Field(default="demo", min_length=1, max_length=100)


class VoiceTurnRequest(BaseModel):
    transcript: str | None = Field(default=None, min_length=1, max_length=4_000)
    audio_base64: str | None = Field(default=None, max_length=12_000_000)
    audio_content_type: str = Field(default="audio/mpeg", max_length=100)
    synthesize: bool = True


class VoiceTurnResponse(BaseModel):
    transcript: str
    reply: str
    route: str
    exit_state: str
    gate_passed: bool
    audio_base64: str | None = None
    audio_content_type: str | None = None
    audio_status: str
    action_status: str | None = None


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy", "service": "marshall", "version": "0.2.0"}


@app.get("/ready")
async def ready() -> dict[str, str]:
    return {"status": "ready", "service": "marshall"}


@app.post("/api/auth/demo-token")
async def create_demo_token(body: DemoTokenRequest) -> dict[str, Any]:
    """Mint a local-only token for testing the JWT boundary."""
    if os.environ.get("AUTH_MODE", "demo").lower() != "demo":
        raise HTTPException(status_code=404, detail="demo token endpoint disabled")
    try:
        token = issue_token(
            customer_id=body.customer_id,
            tenant_id=body.tenant_id,
            auth_level=body.auth_level,
        )
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=500, detail="JWT demo configuration invalid") from exc
    return {"access_token": token, "token_type": "bearer"}


# ── Chat channel ──────────────────────────────────────────────────────────────

@app.post("/api/chat/sessions")
async def create_chat_session(
    body: CreateSessionRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Create a chat session. The server derives identity; the client gets an
    opaque session_id it must present on every message."""
    identity = resolve_identity(
        authorization,
        fallback_customer_id=body.customer_id,
        fallback_auth_level=body.auth_level,
        fallback_tenant_id=body.tenant_id,
    )
    if identity.auth_level not in ("anonymous", "verified"):
        raise HTTPException(status_code=400, detail="chat requires anonymous or verified auth")
    session = await chat_sessions.create(
        customer_id=identity.customer_id,
        auth_level=identity.auth_level,
        tenant_id=identity.tenant_id,
    )
    logger.info(
        "Chat session created: %s customer=%s auth=%s",
        session.session_id, session.customer_id, session.auth_level.value,
    )
    return {
        "session_id": session.session_id,
        "conversation_id": session.conversation_id,
        "customer_id": session.customer_id,
        "tenant_id": session.tenant_id,
        "auth_level": session.auth_level.value,
    }


@app.post("/api/chat/sessions/{session_id}/messages")
async def send_chat_message(
    session_id: str,
    body: MessageRequest,
    authorization: str | None = Header(default=None),
) -> MessageResponse:
    """Run one turn for an existing chat session."""
    identity = resolve_identity(authorization)
    session = await chat_sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    enforce_session_access(identity, session, authorization)

    result = await runtime().run_turn(
        utterance=body.message,
        conversation_id=session.conversation_id,
        customer_id=session.customer_id,
        auth_level=session.auth_level,
        channel=Channel.CHAT,
    )

    await chat_sessions.append_message(session_id, "user", body.message)
    await chat_sessions.append_message(session_id, "assistant", result["reply"])

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
async def get_chat_history(
    session_id: str,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Return the bounded transcript for a session."""
    identity = resolve_identity(authorization)
    session = await chat_sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    enforce_session_access(identity, session, authorization)
    return {"session_id": session_id, "messages": session.messages}


# ── Voice channel ────────────────────────────────────────────────────────────

@app.post("/api/voice/sessions")
async def create_voice_session(
    body: CreateVoiceSessionRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Create a voice session with server-owned identity."""
    identity = resolve_identity(
        authorization,
        fallback_customer_id=body.customer_id,
        fallback_auth_level=body.auth_level,
        fallback_tenant_id=body.tenant_id,
    )
    session = await voice_sessions.create(
        customer_id=identity.customer_id,
        auth_level=identity.auth_level,
        tenant_id=identity.tenant_id,
    )
    provider = voice_provider()
    return {
        "session_id": session.session_id,
        "conversation_id": session.conversation_id,
        "customer_id": session.customer_id,
        "tenant_id": session.tenant_id,
        "auth_level": session.auth_level.value,
        "provider": "elevenlabs" if provider.available else "unconfigured",
    }


@app.post("/api/voice/sessions/{session_id}/turns")
async def send_voice_turn(
    session_id: str,
    body: VoiceTurnRequest,
    authorization: str | None = Header(default=None),
) -> VoiceTurnResponse:
    """Transcribe optional audio, run Taylor, and optionally synthesize a reply.

    Transcript input makes the endpoint usable without paid services. Audio
    input requires a configured ElevenLabs provider.
    """
    identity = resolve_identity(authorization)
    session = await voice_sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="voice session not found")
    enforce_session_access(identity, session, authorization)
    if body.transcript is None and body.audio_base64 is None:
        raise HTTPException(
            status_code=422,
            detail="provide transcript or audio_base64",
        )
    if body.transcript is not None and body.audio_base64 is not None:
        raise HTTPException(
            status_code=422,
            detail="provide transcript or audio_base64, not both",
        )
    if not body.audio_content_type.startswith("audio/"):
        raise HTTPException(status_code=422, detail="audio_content_type must be audio/*")

    transcript = body.transcript
    provider = voice_provider()
    if body.audio_base64 is not None:
        if not provider.available:
            raise HTTPException(
                status_code=503,
                detail="voice transcription provider is not configured",
            )
        try:
            audio = decode_audio_base64(body.audio_base64)
            transcript = await provider.transcribe(audio, body.audio_content_type)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except VoiceProviderError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    assert transcript is not None
    result = await runtime().run_turn(
        utterance=transcript,
        conversation_id=session.conversation_id,
        customer_id=session.customer_id,
        auth_level=session.auth_level,
        channel=Channel.VOICE,
    )
    await voice_sessions.append_turn(session_id, transcript, result["reply"])

    audio_base64 = None
    audio_status = "not_requested"
    if body.synthesize:
        if not provider.available:
            audio_status = "provider_unconfigured"
        else:
            try:
                audio = await provider.synthesize(result["reply"])
                audio_base64 = base64.b64encode(audio).decode("ascii")
                audio_status = "ready"
            except VoiceProviderError:
                logger.warning("Voice synthesis failed", exc_info=True)
                audio_status = "provider_error"

    gate = result.get("gate_result") or {}
    return VoiceTurnResponse(
        transcript=transcript,
        reply=result["reply"],
        route=str(result["route"]),
        exit_state=str(result["exit_state"]),
        gate_passed=bool(gate.get("gate_passed", False)),
        audio_base64=audio_base64,
        audio_content_type="audio/mpeg" if audio_base64 else None,
        audio_status=audio_status,
        action_status=result.get("action_status"),
    )


@app.get("/api/voice/sessions/{session_id}/turns")
async def get_voice_history(
    session_id: str,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    identity = resolve_identity(authorization)
    session = await voice_sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="voice session not found")
    enforce_session_access(identity, session, authorization)
    return {"session_id": session_id, "turns": session.turns}


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
  <h1>Taylor — Agentic Servicing Platform (web chat demo)</h1>
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
