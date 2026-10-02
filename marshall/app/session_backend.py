"""Memory and Redis JSON session backends."""

from __future__ import annotations

import json
import os
from typing import Any

from redis.asyncio import Redis


class MemoryJsonBackend:
    """Deterministic backend used by local development and tests."""

    def __init__(self) -> None:
        self._values: dict[str, dict[str, Any]] = {}

    async def get(self, key: str) -> dict[str, Any] | None:
        value = self._values.get(key)
        return dict(value) if value is not None else None

    async def set(self, key: str, value: dict[str, Any], ttl_seconds: int) -> None:
        del ttl_seconds
        self._values[key] = dict(value)

    async def delete_all(self) -> None:
        self._values.clear()


class RedisJsonBackend:
    """Redis-backed JSON storage with bounded TTLs."""

    def __init__(
        self,
        url: str | None = None,
        namespace: str = "agentic",
        ttl_seconds: int | None = None,
    ) -> None:
        self._client: Redis = Redis.from_url(
            url or os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
            decode_responses=True,
        )
        self._namespace = namespace
        self._ttl_seconds = ttl_seconds or int(
            os.environ.get("SESSION_TTL_SECONDS", "3600")
        )

    def _key(self, key: str) -> str:
        return f"{self._namespace}:session:{key}"

    async def get(self, key: str) -> dict[str, Any] | None:
        raw = await self._client.get(self._key(key))
        return json.loads(raw) if raw else None

    async def set(self, key: str, value: dict[str, Any], ttl_seconds: int) -> None:
        await self._client.setex(
            self._key(key),
            ttl_seconds or self._ttl_seconds,
            json.dumps(value, separators=(",", ":")),
        )

    async def delete_all(self) -> None:
        keys = [key async for key in self._client.scan_iter(f"{self._namespace}:session:*")]
        if keys:
            await self._client.delete(*keys)

    async def close(self) -> None:
        await self._client.aclose()


def build_session_backend(kind: str | None = None):
    selected = (kind or os.environ.get("SESSION_STORE", "memory")).lower()
    if selected == "redis":
        return RedisJsonBackend()
    if selected == "memory":
        return MemoryJsonBackend()
    raise ValueError("SESSION_STORE must be memory or redis")
