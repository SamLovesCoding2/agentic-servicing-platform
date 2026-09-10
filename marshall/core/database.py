"""
Database persistence for the Salient Replica.

Uses SQLAlchemy async with asyncpg to persist:
  - Tool actions (the execution evidence chain)
  - Authorization artifacts (versioned consent)
  - Sessions (conversation runtime state)
  - Audit events (immutable evidence)

The turn coordinator calls these after each turn to persist state.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


# ── ORM Models ───────────────────────────────────────────────────────────────

class ToolAction(Base):
    __tablename__ = "tool_actions"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=lambda: str(uuid4()))
    action_id: Mapped[str] = mapped_column(sa.String(255), unique=True, nullable=False)
    conversation_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    turn_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    customer_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    action_type: Mapped[str] = mapped_column(sa.String(100), nullable=False)
    status: Mapped[str] = mapped_column(sa.String(50), nullable=False, default="PROPOSED")
    intent: Mapped[dict] = mapped_column(sa.JSON, nullable=False, default=dict)
    authorization_ref: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    provider_request_id: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    provider_response: Mapped[dict | None] = mapped_column(sa.JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(sa.TIMESTAMP(timezone=True), server_default=sa.func.now())
    updated_at: Mapped[datetime] = mapped_column(sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now())


class AuthorizationArtifact(Base):
    __tablename__ = "authorization_artifacts"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=lambda: str(uuid4()))
    artifact_id: Mapped[str] = mapped_column(sa.String(255), unique=True, nullable=False)
    customer_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    action_type: Mapped[str] = mapped_column(sa.String(100), nullable=False)
    actor: Mapped[dict] = mapped_column(sa.JSON, nullable=False)
    bound_values: Mapped[dict] = mapped_column(sa.JSON, nullable=False)
    disclosures: Mapped[dict] = mapped_column(sa.JSON, nullable=False)
    version: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=1)
    is_valid: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)
    invalidated_reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(sa.TIMESTAMP(timezone=True), server_default=sa.func.now())
    invalidated_at: Mapped[datetime | None] = mapped_column(sa.TIMESTAMP(timezone=True), nullable=True)


class SessionRecord(Base):
    __tablename__ = "sessions"

    conversation_id: Mapped[str] = mapped_column(sa.String(255), primary_key=True)
    customer_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    auth_level: Mapped[str] = mapped_column(sa.String(50), nullable=False, default="anonymous")
    locale: Mapped[str] = mapped_column(sa.String(10), nullable=False, default="en-US")
    channel: Mapped[str] = mapped_column(sa.String(20), nullable=False)
    collected_slots: Mapped[dict] = mapped_column(sa.JSON, nullable=False, default=dict)
    pending_confirmation: Mapped[dict | None] = mapped_column(sa.JSON, nullable=True)
    state_version: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(sa.TIMESTAMP(timezone=True), server_default=sa.func.now())
    updated_at: Mapped[datetime] = mapped_column(sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now())


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=lambda: str(uuid4()))
    conversation_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    turn_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    customer_id: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(sa.String(100), nullable=False)
    event_data: Mapped[dict] = mapped_column(sa.JSON, nullable=False, default=dict)
    model_version: Mapped[str | None] = mapped_column(sa.String(100), nullable=True)
    config_version: Mapped[str | None] = mapped_column(sa.String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(sa.TIMESTAMP(timezone=True), server_default=sa.func.now())


# ── Database Manager ─────────────────────────────────────────────────────────

class Database:
    """
    Async database manager.

    Handles connections, table creation, and persistence operations.
    """

    def __init__(self, database_url: str | None = None):
        self._url = database_url or os.environ.get(
            "DATABASE_URL",
            "postgresql+asyncpg://salient:salient@localhost:5432/salient",
        )
        self._engine = None

    @property
    def engine(self):
        if self._engine is None:
            self._engine = create_async_engine(self._url, echo=False)
        return self._engine

    async def create_tables(self):
        """Create all tables (for development/testing)."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables created")

    async def drop_tables(self):
        """Drop all tables (for testing)."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

    async def save_tool_action(
        self,
        action_id: str,
        conversation_id: str,
        turn_id: str,
        customer_id: str,
        action_type: str,
        status: str,
        intent: dict[str, Any],
        authorization_ref: str | None = None,
        provider_request_id: str | None = None,
        provider_response: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> ToolAction:
        """Persist a tool action (the execution evidence chain)."""
        async with AsyncSession(self.engine) as session:
            action = ToolAction(
                action_id=action_id,
                conversation_id=conversation_id,
                turn_id=turn_id,
                customer_id=customer_id,
                action_type=action_type,
                status=status,
                intent=intent,
                authorization_ref=authorization_ref,
                provider_request_id=provider_request_id,
                provider_response=provider_response,
                error_message=error_message,
            )
            session.add(action)
            await session.commit()
            logger.info(f"Saved tool action: {action_id} status={status}")
            return action

    async def save_authorization_artifact(
        self,
        artifact: dict[str, Any],
    ) -> AuthorizationArtifact:
        """Persist a versioned authorization artifact."""
        async with AsyncSession(self.engine) as session:
            record = AuthorizationArtifact(
                artifact_id=artifact["artifact_id"],
                customer_id=artifact["customer_id"],
                action_type=artifact["action_type"],
                actor=artifact["actor"],
                bound_values=artifact["bound_values"],
                disclosures=artifact["disclosures"],
                version=artifact.get("version", 1),
                is_valid=artifact.get("is_valid", True),
            )
            session.add(record)
            await session.commit()
            logger.info(f"Saved authorization artifact: {artifact['artifact_id']}")
            return record

    async def save_session(
        self,
        conversation_id: str,
        customer_id: str,
        auth_level: str,
        channel: str,
        collected_slots: dict[str, Any] | None = None,
        pending_confirmation: dict[str, Any] | None = None,
    ) -> SessionRecord:
        """Insert or update a session record."""
        async with AsyncSession(self.engine) as session:
            # Try to find existing
            stmt = sa.select(SessionRecord).where(SessionRecord.conversation_id == conversation_id)
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing:
                existing.auth_level = auth_level
                existing.collected_slots = collected_slots or {}
                existing.pending_confirmation = pending_confirmation
                existing.state_version += 1
            else:
                record = SessionRecord(
                    conversation_id=conversation_id,
                    customer_id=customer_id,
                    auth_level=auth_level,
                    channel=channel,
                    collected_slots=collected_slots or {},
                    pending_confirmation=pending_confirmation,
                )
                session.add(record)

            await session.commit()
            return existing or record

    async def save_audit_event(
        self,
        conversation_id: str,
        turn_id: str,
        customer_id: str,
        event_type: str,
        event_data: dict[str, Any],
        model_version: str | None = None,
    ) -> AuditEvent:
        """Persist an immutable audit event."""
        async with AsyncSession(self.engine) as session:
            event = AuditEvent(
                conversation_id=conversation_id,
                turn_id=turn_id,
                customer_id=customer_id,
                event_type=event_type,
                event_data=event_data,
                model_version=model_version,
            )
            session.add(event)
            await session.commit()
            return event

    async def get_tool_action(self, action_id: str) -> ToolAction | None:
        """Retrieve a tool action by action_id (for reconciliation)."""
        async with AsyncSession(self.engine) as session:
            stmt = sa.select(ToolAction).where(ToolAction.action_id == action_id)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def close(self):
        """Dispose of the engine."""
        if self._engine:
            await self._engine.dispose()
