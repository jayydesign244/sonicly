"""ElevenLabs adapter: Instant Voice Clone + TTS.

Two operations:
  - clone_voice(audio_bytes, name) → voice_id (persisted on the Project)
  - synthesize(voice_id, text)     → mp3 bytes (used to regenerate a word
                                     or phrase in the user's voice)

Both call the public ElevenLabs REST API via httpx; no SDK dependency.

When the ElevenLabs plan doesn't include Instant Voice Cloning, callers
can fall back to ELEVENLABS_FALLBACK_VOICE_ID (a premade voice that's
available on every plan). That keeps the replace flow demoable without
forcing a paid plan; the version label makes it obvious it's not the
user's real voice.

Requests are wrapped in an exponential-backoff retry on 429 and 5xx so a
single rate-limit blip during a multi-word replace doesn't fail the
whole apply.
"""
import asyncio
import json
import os
import random
from typing import Awaitable, Callable, Optional

import httpx

ELEVENLABS_BASE = "https://api.elevenlabs.io/v1"
ELEVENLABS_TTS_MODEL = os.environ.get("ELEVENLABS_TTS_MODEL", "eleven_turbo_v2_5")
# "Sarah" — a neutral premade voice available on every plan.
FALLBACK_VOICE_ID = os.environ.get(
    "ELEVENLABS_FALLBACK_VOICE_ID", "EXAVITQu4vr4xnSDxMaL"
)
FALLBACK_VOICE_PROVIDER = "elevenlabs-premade"


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
    def __init__(self, message: str, *, plan_upgrade_required: bool = False, status_code: Optional[int] = None):
        super().__init__(message)
        self.plan_upgrade_required = plan_upgrade_required
        self.status_code = status_code


_MAX_RETRIES = int(os.environ.get("ELEVENLABS_MAX_RETRIES", "3"))
_BASE_BACKOFF = float(os.environ.get("ELEVENLABS_BASE_BACKOFF", "0.75"))
_RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}


async def _request_with_retry(
    send: Callable[[httpx.AsyncClient], Awaitable[httpx.Response]],
    *,
    timeout: float,
) -> httpx.Response:
    """Call `send(client)` with exponential backoff on transient errors.

    Retries on 429/5xx (honouring Retry-After when present) and on
    network errors. Non-retryable 4xx responses are returned as-is for
    the caller to translate via `_parse_error`.
    """
    last_exc: Optional[Exception] = None
    async with httpx.AsyncClient(timeout=timeout) as client:
        for attempt in range(_MAX_RETRIES + 1):
            try:
                resp = await send(client)
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_exc = exc
                resp = None
            else:
                if resp.status_code not in _RETRY_STATUS:
                    return resp
                last_exc = None

            if attempt == _MAX_RETRIES:
                if resp is not None:
                    return resp
                raise VoiceError(f"Network error talking to ElevenLabs: {last_exc}")

            delay = _BASE_BACKOFF * (2 ** attempt)
            if resp is not None:
                retry_after = resp.headers.get("retry-after")
                if retry_after:
                    try:
                        delay = max(delay, float(retry_after))
                    except ValueError:
                        pass
            delay += random.uniform(0, _BASE_BACKOFF)
            await asyncio.sleep(delay)

    raise VoiceError("Unreachable retry loop exit")


def _parse_error(resp: httpx.Response) -> VoiceError:
    """Build a VoiceError that carries the upgrade-required flag when the
    API returns paid_plan_required (free-tier limitation for IVC)."""
    try:
        body = resp.json()
    except json.JSONDecodeError:
        body = {}
    detail = body.get("detail") if isinstance(body, dict) else None
    detail_status = ""
    detail_msg = resp.text[:400]
    upgrade = False
    if isinstance(detail, dict):
        detail_status = detail.get("status") or ""
        detail_msg = detail.get("message") or detail_msg
        upgrade = detail.get("type") == "payment_required" or detail_status == "can_not_use_instant_voice_cloning"
    return VoiceError(
        detail_msg,
        plan_upgrade_required=upgrade,
        status_code=resp.status_code,
    )


async def clone_voice(audio_bytes: bytes, name: str, content_type: str = "audio/mpeg") -> str:
    """Create an Instant Voice Clone from the given audio sample.

    Returns the new voice_id. Raises VoiceError on failure.
    """
    if not is_configured():
        raise VoiceError("ELEVENLABS_API_KEY not configured")

    data = {
        "name": name[:100] or "Sonicly voice",
        "description": "Cloned by Sonicly for transcript-based edits",
    }

    async def _send(client: httpx.AsyncClient) -> httpx.Response:
        return await client.post(
            f"{ELEVENLABS_BASE}/voices/add",
            headers=_headers(),
            data=data,
            files={"files": (f"{name}.mp3", audio_bytes, content_type)},
        )

    resp = await _request_with_retry(_send, timeout=120.0)
    if resp.status_code >= 400:
        raise _parse_error(resp)
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
    async def _send(client: httpx.AsyncClient) -> httpx.Response:
        return await client.post(
            f"{ELEVENLABS_BASE}/text-to-speech/{voice_id}",
            headers=_headers({"Content-Type": "application/json", "Accept": "audio/mpeg"}),
            json=payload,
        )

    resp = await _request_with_retry(_send, timeout=120.0)
    if resp.status_code >= 400:
        raise _parse_error(resp)
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
