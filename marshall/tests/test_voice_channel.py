from __future__ import annotations

import base64

import httpx

from marshall.app import main
from marshall.app.voice_provider import (
    DeterministicVoiceProvider,
    ElevenLabsConfig,
    ElevenLabsVoiceProvider,
    VoiceProviderError,
)


async def test_elevenlabs_provider_uses_documented_request_shapes():
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["xi-api-key"] == "test-eleven-key"
        if request.url.path == "/v1/speech-to-text":
            return httpx.Response(200, json={"text": "what is my balance"})
        assert request.url.path == "/v1/text-to-speech/voice-123"
        assert request.url.params["output_format"] == "mp3_44100_128"
        return httpx.Response(200, content=b"fake-mp3")

    config = ElevenLabsConfig(
        api_key="test-eleven-key",
        voice_id="voice-123",
        base_url="https://api.elevenlabs.io",
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url=config.base_url,
    ) as client:
        provider = ElevenLabsVoiceProvider(config=config, client=client)
        assert await provider.transcribe(b"fake-input", "audio/mpeg") == "what is my balance"
        assert await provider.synthesize("Hello") == b"fake-mp3"

    assert len(requests) == 2


async def test_elevenlabs_provider_hides_provider_error_body():
    async def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            401,
            content=b"secret provider diagnostic that must not escape",
        )

    config = ElevenLabsConfig(api_key="test-key", voice_id="voice-123")
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url=config.base_url,
    ) as client:
        provider = ElevenLabsVoiceProvider(config=config, client=client)
        try:
            await provider.synthesize("Hello")
        except VoiceProviderError as exc:
            assert str(exc) == "ElevenLabs request failed with HTTP 401"
        else:
            raise AssertionError("provider error was not raised")


def test_transcript_voice_turn_is_free_and_deterministic(client, monkeypatch):
    monkeypatch.setattr(main, "_VOICE_PROVIDER", DeterministicVoiceProvider())
    response = client.post("/api/voice/sessions", json={"customer_id": "voice-cust"})
    assert response.status_code == 200
    session_id = response.json()["session_id"]
    assert response.json()["provider"] == "elevenlabs"

    response = client.post(
        f"/api/voice/sessions/{session_id}/turns",
        json={
            "transcript": "What happens if I miss a payment?",
            "synthesize": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["transcript"] == "What happens if I miss a payment?"
    assert body["route"] == "knowledge"
    assert body["gate_passed"] is True
    assert body["audio_status"] == "ready"
    assert base64.b64decode(body["audio_base64"]) == b"deterministic-audio"


def test_audio_requires_configured_provider(client, monkeypatch):
    monkeypatch.setattr(
        main,
        "_VOICE_PROVIDER",
        ElevenLabsVoiceProvider(
            ElevenLabsConfig(api_key="", voice_id=""),
        ),
    )
    response = client.post("/api/voice/sessions", json={})
    session_id = response.json()["session_id"]

    response = client.post(
        f"/api/voice/sessions/{session_id}/turns",
        json={"audio_base64": base64.b64encode(b"fake-audio").decode()},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "voice transcription provider is not configured"


def test_voice_transcript_is_bounded_in_history(client, monkeypatch):
    monkeypatch.setattr(main, "_VOICE_PROVIDER", DeterministicVoiceProvider())
    session_id = client.post("/api/voice/sessions", json={}).json()["session_id"]

    for _ in range(30):
        response = client.post(
            f"/api/voice/sessions/{session_id}/turns",
            json={"transcript": "hello", "synthesize": False},
        )
        assert response.status_code == 200

    history = client.get(f"/api/voice/sessions/{session_id}/turns").json()
    assert len(history["turns"]) == 25
