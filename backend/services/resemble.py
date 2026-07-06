"""Resemble AI adapter: voice cloning + TTS.

Mirrors the surface of `services/voice.py` (ElevenLabs) so callers can
choose a provider per-feature later without changing call sites:

  - clone_voice(audio_bytes, name) -> voice_uuid
  - synthesize(voice_uuid, text)   -> wav/mp3 bytes

Authentication: `Authorization: Token <RESEMBLE_API_KEY>`.

Endpoints used:
  - REST v2:   https://app.resemble.ai/api/v2
  - Sync TTS:  https://f.cluster.resemble.ai/synthesize
    (returns JSON with base64-encoded audio in `audio_content`)

A project UUID (RESEMBLE_PROJECT_UUID) is required for the sync TTS
endpoint; create one once in the Resemble dashboard or via
POST /api/v2/projects.
"""
import base64
import os
from typing import Optional

import httpx

RESEMBLE_REST_BASE = "https://app.resemble.ai/api/v2"
RESEMBLE_SYNTH_URL = "https://f.cluster.resemble.ai/synthesize"

DEFAULT_SAMPLE_RATE = int(os.environ.get("RESEMBLE_SAMPLE_RATE", "22050"))
DEFAULT_OUTPUT_FORMAT = os.environ.get("RESEMBLE_OUTPUT_FORMAT", "wav")


def _api_key() -> Optional[str]:
    return os.environ.get("RESEMBLE_API_KEY") or None


def _project_uuid() -> Optional[str]:
    return os.environ.get("RESEMBLE_PROJECT_UUID") or None


def is_configured() -> bool:
    return bool(_api_key())


def _headers(extra: Optional[dict] = None) -> dict:
    h = {"Authorization": f"Token {_api_key() or ''}"}
    if extra:
        h.update(extra)
    return h


class ResembleError(RuntimeError):
    """Raised when Resemble returns an error or is not configured."""
    def __init__(self, message: str, *, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


def _parse_error(resp: httpx.Response) -> ResembleError:
    detail = resp.text[:400]
    try:
        body = resp.json()
        if isinstance(body, dict):
            detail = body.get("message") or body.get("error") or detail
    except ValueError:
        pass
    return ResembleError(detail, status_code=resp.status_code)


async def clone_voice(audio_bytes: bytes, name: str, content_type: str = "audio/mpeg") -> str:
    """Create a Resemble voice from a sample.

    Two-step flow:
      1. POST /voices              -> voice_uuid
      2. POST /voices/{uuid}/recordings (multipart) with the sample

    Returns the voice_uuid. Raises ResembleError on failure.
    """
    if not is_configured():
        raise ResembleError("RESEMBLE_API_KEY not configured")

    async with httpx.AsyncClient(timeout=120.0) as client:
        create_resp = await client.post(
            f"{RESEMBLE_REST_BASE}/voices",
            headers=_headers({"Content-Type": "application/json"}),
            json={"name": (name[:100] or "EigenTalk voice"), "dataset_url": None},
        )
        if create_resp.status_code >= 400:
            raise _parse_error(create_resp)
        created = create_resp.json()
        voice_uuid = (created.get("item") or {}).get("uuid") or created.get("uuid")
        if not voice_uuid:
            raise ResembleError(f"No voice uuid in response: {created}")

        files = {"file": (f"{name}.mp3", audio_bytes, content_type)}
        data = {"name": name[:100] or "sample", "text": ""}
        upload_resp = await client.post(
            f"{RESEMBLE_REST_BASE}/voices/{voice_uuid}/recordings",
            headers=_headers(),
            data=data,
            files=files,
        )
        if upload_resp.status_code >= 400:
            raise _parse_error(upload_resp)

    return voice_uuid


async def synthesize(
    voice_uuid: str,
    text: str,
    *,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    output_format: str = DEFAULT_OUTPUT_FORMAT,
) -> bytes:
    """Generate audio bytes for `text` in the given voice.

    Uses Resemble's synchronous synthesis endpoint, which returns audio
    bytes directly. Requires RESEMBLE_PROJECT_UUID.
    """
    if not is_configured():
        raise ResembleError("RESEMBLE_API_KEY not configured")
    project_uuid = _project_uuid()
    if not project_uuid:
        raise ResembleError("RESEMBLE_PROJECT_UUID not configured")

    payload = {
        "voice_uuid": voice_uuid,
        "project_uuid": project_uuid,
        "data": text,
        "sample_rate": sample_rate,
        "output_format": output_format,
        "precision": "PCM_16",
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            RESEMBLE_SYNTH_URL,
            headers=_headers({"Content-Type": "application/json"}),
            json=payload,
        )
    if resp.status_code >= 400:
        raise _parse_error(resp)
    body = resp.json()
    if not body.get("success"):
        raise ResembleError(
            body.get("issues") or body.get("message") or "synthesis failed",
            status_code=resp.status_code,
        )
    audio_b64 = body.get("audio_content")
    if not audio_b64:
        raise ResembleError(f"No audio_content in response: {list(body.keys())}")
    return base64.b64decode(audio_b64)


async def delete_voice(voice_uuid: str) -> None:
    """Best-effort cleanup. Silent on failure."""
    if not is_configured():
        return
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            await client.delete(
                f"{RESEMBLE_REST_BASE}/voices/{voice_uuid}",
                headers=_headers(),
            )
        except httpx.HTTPError:
            pass
