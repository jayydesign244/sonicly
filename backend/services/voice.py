"""ElevenLabs adapter: Instant Voice Clone + TTS.

Two operations:
  - clone_voice(audio_bytes, name) → voice_id (persisted on the Project)
  - synthesize(voice_id, text)     → mp3 bytes (used to regenerate a word
                                     or phrase in the user's voice)

Both call the public ElevenLabs REST API via httpx; no SDK dependency.
"""
import os
from typing import Optional

import httpx

ELEVENLABS_BASE = "https://api.elevenlabs.io/v1"
ELEVENLABS_TTS_MODEL = os.environ.get("ELEVENLABS_TTS_MODEL", "eleven_turbo_v2_5")


def _api_key() -> Optional[str]:
    return os.environ.get("ELEVENLABS_API_KEY") or None


def is_configured() -> bool:
    return bool(_api_key())


def _headers(extra: Optional[dict] = None) -> dict:
    h = {"xi-api-key": _api_key() or ""}
    if extra:
        h.update(extra)
    return h


class VoiceError(RuntimeError):
    """Raised when ElevenLabs returns an error or is not configured."""


async def clone_voice(audio_bytes: bytes, name: str, content_type: str = "audio/mpeg") -> str:
    """Create an Instant Voice Clone from the given audio sample.

    Returns the new voice_id. Raises VoiceError on failure.
    """
    if not is_configured():
        raise VoiceError("ELEVENLABS_API_KEY not configured")

    files = {"files": (f"{name}.mp3", audio_bytes, content_type)}
    data = {
        "name": name[:100] or "Sonicly voice",
        "description": "Cloned by Sonicly for transcript-based edits",
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{ELEVENLABS_BASE}/voices/add",
            headers=_headers(),
            data=data,
            files=files,
        )
    if resp.status_code >= 400:
        raise VoiceError(f"Voice clone failed ({resp.status_code}): {resp.text[:400]}")
    body = resp.json()
    voice_id = body.get("voice_id")
    if not voice_id:
        raise VoiceError(f"No voice_id in response: {body}")
    return voice_id


async def synthesize(
    voice_id: str,
    text: str,
    *,
    stability: float = 0.5,
    similarity_boost: float = 0.85,
    style: float = 0.0,
) -> bytes:
    """Generate mp3 bytes for `text` in the given cloned voice.

    `similarity_boost` is cranked toward the source voice so single-word
    inserts blend with the surrounding audio. `stability` is moderate
    so short utterances retain prosody.
    """
    if not is_configured():
        raise VoiceError("ELEVENLABS_API_KEY not configured")

    payload = {
        "text": text,
        "model_id": ELEVENLABS_TTS_MODEL,
        "voice_settings": {
            "stability": stability,
            "similarity_boost": similarity_boost,
            "style": style,
            "use_speaker_boost": True,
        },
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{ELEVENLABS_BASE}/text-to-speech/{voice_id}",
            headers=_headers({"Content-Type": "application/json", "Accept": "audio/mpeg"}),
            json=payload,
        )
    if resp.status_code >= 400:
        raise VoiceError(f"TTS failed ({resp.status_code}): {resp.text[:400]}")
    return resp.content


async def delete_voice(voice_id: str) -> None:
    """Best-effort cleanup. We don't currently call this — kept for the
    settings page later. Failures are silent because ElevenLabs sometimes
    holds clones for a billing period."""
    if not is_configured():
        return
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            await client.delete(f"{ELEVENLABS_BASE}/voices/{voice_id}", headers=_headers())
        except httpx.HTTPError:
            pass
