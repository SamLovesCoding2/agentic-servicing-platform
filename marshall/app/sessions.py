"""Chat session registry.

Server-side session authority for the web chat channel.

The chat channel intentionally keeps a NARROW tool surface: payment
execution is excluded (the router blocks `sensitive_action` for chat and
the channel override omits `schedule_payment`). Identity is server-derived
at session creation — a client cannot claim a customer_id or auth_level;
in production these come from the platform auth provider (JWT), which M7
will introduce. For the local demo we accept a callers-chosen customer tag.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from taylor.graphs.universal.state import AuthLevel


@dataclass
class ChatSession:
    session_id: str
    conversation_id: str
    customer_id: str
    auth_level: AuthLevel
    created_at: float
    messages: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "conversation_id": self.conversation_id,
            "customer_id": self.customer_id,
            "auth_level": self.auth_level.value,
            "messages": self.messages,
        }


class ChatSessionManager:
    """In-memory session store. Replaced by a persistent store in production."""

    def __init__(self) -> None:
        self._sessions: dict[str, ChatSession] = {}

    def create(
        self,
        customer_id: str = "cust_demo_001",
        auth_level: str = "verified",
    ) -> ChatSession:
        session = ChatSession(
            session_id=str(uuid4()),
            conversation_id=f"chat_{uuid4().hex[:12]}",
            customer_id=customer_id,
            auth_level=AuthLevel(auth_level),
            created_at=time.time(),
        )
        self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> ChatSession | None:
        return self._sessions.get(session_id)

    def append_message(self, session_id: str, role: str, content: str) -> None:
        session = self.get(session_id)
        if session:
            session.messages.append({"role": role, "content": content})
            # Keep the transcript bounded.
            session.messages = session.messages[-50:]

    def clear(self) -> None:
        self._sessions.clear()


chat_sessions = ChatSessionManager()
