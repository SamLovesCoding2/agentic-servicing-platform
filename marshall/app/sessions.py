"""Chat session registry.

Server-side session authority for the web chat channel.

The chat channel intentionally keeps a NARROW tool surface: payment
execution is excluded (the router blocks `sensitive_action` for chat and
the channel override omits `schedule_payment`). Identity is server-derived
at session creation — a client cannot claim a customer_id or auth_level;
in production these come from the platform auth provider (JWT). The backend
can be switched from memory to Redis with ``SESSION_STORE=redis``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from marshall.app.session_backend import build_session_backend
from taylor.graphs.universal.state import AuthLevel


@dataclass
class ChatSession:
    session_id: str
    conversation_id: str
    customer_id: str
    tenant_id: str
    auth_level: AuthLevel
    created_at: float
    messages: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "conversation_id": self.conversation_id,
            "customer_id": self.customer_id,
            "tenant_id": self.tenant_id,
            "auth_level": self.auth_level.value,
            "created_at": self.created_at,
            "messages": self.messages,
        }


class ChatSessionManager:
    """In-memory session store. Replaced by a persistent store in production."""

    def __init__(self, backend=None) -> None:
        self._backend = backend or build_session_backend()

    async def create(
        self,
        customer_id: str = "cust_demo_001",
        auth_level: str = "verified",
        tenant_id: str = "demo",
    ) -> ChatSession:
        session = ChatSession(
            session_id=str(uuid4()),
            conversation_id=f"chat_{uuid4().hex[:12]}",
            customer_id=customer_id,
            tenant_id=tenant_id,
            auth_level=AuthLevel(auth_level),
            created_at=time.time(),
        )
        await self._backend.set(session.session_id, session.to_dict(), 0)
        return session

    async def get(self, session_id: str) -> ChatSession | None:
        value = await self._backend.get(session_id)
        if value is None:
            return None
        return ChatSession(
            session_id=value["session_id"],
            conversation_id=value["conversation_id"],
            customer_id=value["customer_id"],
            tenant_id=value.get("tenant_id", "demo"),
            auth_level=AuthLevel(value["auth_level"]),
            created_at=float(value.get("created_at", time.time())),
            messages=list(value.get("messages", [])),
        )

    async def append_message(self, session_id: str, role: str, content: str) -> None:
        session = await self.get(session_id)
        if session:
            session.messages.append({"role": role, "content": content})
            # Keep the transcript bounded.
            session.messages = session.messages[-50:]
            await self._backend.set(session_id, session.to_dict(), 0)

    def clear(self) -> None:
        if hasattr(self._backend, "_values"):
            self._backend._values.clear()

    async def aclear(self) -> None:
        await self._backend.delete_all()


chat_sessions = ChatSessionManager()
