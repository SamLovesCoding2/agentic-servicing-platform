"""Server-owned voice sessions and bounded transcripts."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from marshall.app.session_backend import build_session_backend
from taylor.graphs.universal.state import AuthLevel


@dataclass
class VoiceSession:
    session_id: str
    conversation_id: str
    customer_id: str
    tenant_id: str
    auth_level: AuthLevel
    created_at: float
    turns: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "conversation_id": self.conversation_id,
            "customer_id": self.customer_id,
            "tenant_id": self.tenant_id,
            "auth_level": self.auth_level.value,
            "created_at": self.created_at,
            "turns": self.turns,
        }


class VoiceSessionManager:
    """In-memory voice session store for the local adapter.

    Production deployment should replace this with Redis/Postgres and bind
    customer identity to a verified call/session credential.
    """

    def __init__(self, backend=None) -> None:
        self._backend = backend or build_session_backend()

    async def create(
        self,
        customer_id: str = "cust_demo_001",
        auth_level: str = "verified",
        tenant_id: str = "demo",
    ) -> VoiceSession:
        session = VoiceSession(
            session_id=str(uuid4()),
            conversation_id=f"voice_{uuid4().hex[:12]}",
            customer_id=customer_id,
            tenant_id=tenant_id,
            auth_level=AuthLevel(auth_level),
            created_at=time.time(),
        )
        await self._backend.set(session.session_id, session.to_dict(), 0)
        return session

    async def get(self, session_id: str) -> VoiceSession | None:
        value = await self._backend.get(session_id)
        if value is None:
            return None
        return VoiceSession(
            session_id=value["session_id"],
            conversation_id=value["conversation_id"],
            customer_id=value["customer_id"],
            tenant_id=value.get("tenant_id", "demo"),
            auth_level=AuthLevel(value["auth_level"]),
            created_at=float(value["created_at"]),
            turns=list(value.get("turns", [])),
        )

    async def append_turn(self, session_id: str, transcript: str, reply: str) -> None:
        session = await self.get(session_id)
        if session is None:
            return
        session.turns.append({"transcript": transcript, "reply": reply})
        session.turns = session.turns[-25:]
        await self._backend.set(session_id, session.to_dict(), 0)

    def clear(self) -> None:
        if hasattr(self._backend, "_values"):
            self._backend._values.clear()

    async def aclear(self) -> None:
        await self._backend.delete_all()


voice_sessions = VoiceSessionManager()
