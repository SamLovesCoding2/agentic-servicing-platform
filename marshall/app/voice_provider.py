"""Voice provider boundary with an ElevenLabs implementation.

The agent runtime owns reasoning, authorization, compliance, and response
policy. This module only translates audio/text at the provider boundary.
"""

from __future__ import annotations

import base64
import binascii
import os
from dataclasses import dataclass
from typing import Protocol

import httpx


class VoiceProviderError(RuntimeError):
    """A provider call failed without exposing provider response details."""


class VoiceProviderUnavailableError(VoiceProviderError):
    """The provider is not configured for this process."""


class VoiceProvider(Protocol):
    """Minimal contract required by the voice channel."""

    @property
    def available(self) -> bool:
        """Whether this provider can make external calls."""

    async def transcribe(self, audio: bytes, content_type: str) -> str:
        """Convert an audio payload to a transcript."""

    async def synthesize(self, text: str) -> bytes:
        """Convert response text to audio bytes."""


@dataclass(frozen=True)
class ElevenLabsConfig:
    """Runtime configuration for the ElevenLabs REST API."""

    api_key: str
    voice_id: str
    model_id: str = "eleven_multilingual_v2"
    output_format: str = "mp3_44100_128"
    base_url: str = "https://api.elevenlabs.io"
    timeout_seconds: float = 30.0
    stt_model_id: str = "scribe_v2"

    @classmethod
    def from_environment(cls) -> ElevenLabsConfig:
        return cls(
            api_key=os.environ.get("ELEVENLABS_API_KEY", ""),
            voice_id=os.environ.get("ELEVENLABS_VOICE_ID", ""),
            model_id=os.environ.get("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2"),
            output_format=os.environ.get(
                "ELEVENLABS_OUTPUT_FORMAT",
                "mp3_44100_128",
            ),
            base_url=os.environ.get(
                "ELEVENLABS_BASE_URL",
                "https://api.elevenlabs.io",
            ).rstrip("/"),
            timeout_seconds=float(
                os.environ.get("ELEVENLABS_TIMEOUT_SECONDS", "30")
            ),
            stt_model_id=os.environ.get("ELEVENLABS_STT_MODEL_ID", "scribe_v2"),
        )


class ElevenLabsVoiceProvider:
    """ElevenLabs text-to-speech and speech-to-text adapter.

    The client is injectable for tests. The production path uses httpx and
    the documented ``xi-api-key`` header, keeping the official API boundary
    explicit and easy to replace.
    """

    def __init__(
        self,
        config: ElevenLabsConfig | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.config = config or ElevenLabsConfig.from_environment()
        self._client = client

    @property
    def available(self) -> bool:
        return bool(self.config.api_key and self.config.voice_id)

    async def transcribe(self, audio: bytes, content_type: str) -> str:
        self._require_available()
        if not audio:
            raise ValueError("audio payload must not be empty")

        response = await self._request(
            "POST",
            "/v1/speech-to-text",
            files={
                "file": (
                    "voice-input",
                    audio,
                    content_type or "application/octet-stream",
                )
            },
            data={"model_id": self.config.stt_model_id},
        )
        try:
            transcript = response.json().get("text", "")
        except ValueError as exc:
            raise VoiceProviderError("ElevenLabs returned invalid transcription JSON") from exc
        if not isinstance(transcript, str) or not transcript.strip():
            raise VoiceProviderError("ElevenLabs returned an empty transcript")
        return transcript.strip()

    async def synthesize(self, text: str) -> bytes:
        self._require_available()
        if not text.strip():
            raise ValueError("text must not be empty")

        response = await self._request(
            "POST",
            f"/v1/text-to-speech/{self.config.voice_id}",
            params={"output_format": self.config.output_format},
            json={
                "text": text,
                "model_id": self.config.model_id,
            },
        )
        if not response.content:
            raise VoiceProviderError("ElevenLabs returned empty audio")
        return response.content

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        headers = {"xi-api-key": self.config.api_key}
        client = self._client
        owns_client = client is None
        if client is None:
            client = httpx.AsyncClient(
                base_url=self.config.base_url,
                timeout=self.config.timeout_seconds,
            )
        try:
            response = await client.request(method, path, headers=headers, **kwargs)
        except httpx.TimeoutException as exc:
            raise VoiceProviderError("ElevenLabs request timed out") from exc
        except httpx.HTTPError as exc:
            raise VoiceProviderError("ElevenLabs request failed") from exc
        finally:
            if owns_client:
                await client.aclose()

        if response.is_error:
            raise VoiceProviderError(
                f"ElevenLabs request failed with HTTP {response.status_code}"
            )
        return response

    def _require_available(self) -> None:
        if not self.available:
            raise VoiceProviderUnavailableError(
                "ElevenLabs is not configured; set ELEVENLABS_API_KEY and "
                "ELEVENLABS_VOICE_ID"
            )


class DeterministicVoiceProvider:
    """Free local provider used by tests and transcript-only demos."""

    def __init__(self, audio_bytes: bytes = b"deterministic-audio") -> None:
        self.audio_bytes = audio_bytes

    @property
    def available(self) -> bool:
        return True

    async def transcribe(self, audio: bytes, content_type: str) -> str:
        del content_type
        if not audio:
            raise ValueError("audio payload must not be empty")
        return "deterministic audio transcript"

    async def synthesize(self, text: str) -> bytes:
        if not text.strip():
            raise ValueError("text must not be empty")
        return self.audio_bytes


def decode_audio_base64(value: str) -> bytes:
    """Decode a request payload while rejecting malformed base64."""
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("audio_base64 must be valid base64") from exc
