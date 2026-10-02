"""Server-owned voice sessions and bounded transcripts."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from taylor.graphs.universal.state import AuthLevel


@dataclass
class VoiceSession:
    session_id: str
    conversation_id: str
    customer_id: str
    auth_level: AuthLevel
    created_at: float
    turns: list[dict[str, Any]] = field(default_factory=list)

    def append_turn(self, transcript: str, reply: str) -> None:
        self.turns.append({"transcript": transcript, "reply": reply})
        self.turns = self.turns[-25:]


class VoiceSessionManager:
    """In-memory voice session store for the local adapter.

    Production deployment should replace this with Redis/Postgres and bind
    customer identity to a verified call/session credential.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, VoiceSession] = {}

    def create(
        self,
        customer_id: str = "cust_demo_001",
        auth_level: str = "verified",
    ) -> VoiceSession:
        session = VoiceSession(
            session_id=str(uuid4()),
            conversation_id=f"voice_{uuid4().hex[:12]}",
            customer_id=customer_id,
            auth_level=AuthLevel(auth_level),
            created_at=time.time(),
        )
        self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> VoiceSession | None:
        return self._sessions.get(session_id)

    def clear(self) -> None:
        self._sessions.clear()


voice_sessions = VoiceSessionManager()
