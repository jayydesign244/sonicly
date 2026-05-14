"""Audio storage. Uses Supabase Storage when configured; otherwise falls back
to a local `uploads/` directory served by the FastAPI app itself."""
import os
import re
import uuid
from pathlib import Path
from typing import Optional

import httpx

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
BUCKET = os.environ.get("SUPABASE_BUCKET", "audio")

# Local fallback — relative to backend/ working directory.
LOCAL_UPLOAD_DIR = Path(os.environ.get("LOCAL_UPLOAD_DIR", "./uploads")).resolve()
LOCAL_PUBLIC_PREFIX = os.environ.get("LOCAL_PUBLIC_PREFIX", "/api/uploads").rstrip("/")
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")


def supabase_configured() -> bool:
    return bool(SUPABASE_URL and SUPABASE_SERVICE_KEY)


# Kept for backwards compatibility with existing callers — now always True
# because the local fallback is always available.
def is_configured() -> bool:
    return True


def _safe_filename(filename: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", filename).strip("_") or "audio"


def _headers(content_type: Optional[str] = None) -> dict:
    h = {
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "apikey": SUPABASE_SERVICE_KEY,
    }
    if content_type:
        h["Content-Type"] = content_type
        h["x-upsert"] = "true"
    return h


async def _upload_supabase(object_path: str, data: bytes, content_type: str) -> str:
    upload_url = f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{object_path}"
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(upload_url, content=data, headers=_headers(content_type))
        resp.raise_for_status()
    return f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET}/{object_path}"


def _upload_local(object_path: str, data: bytes) -> str:
    dest = LOCAL_UPLOAD_DIR / object_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    # Return an absolute URL so the browser (on a different origin) can fetch it.
    return f"{PUBLIC_BASE_URL}{LOCAL_PUBLIC_PREFIX}/{object_path}"


async def upload_audio(
    user_id: str,
    filename: str,
    data: bytes,
    content_type: str = "application/octet-stream",
) -> str:
    """Upload audio bytes; return a publicly fetchable URL."""
    safe_name = _safe_filename(filename)
    object_path = f"{user_id}/{uuid.uuid4().hex}_{safe_name}"

    if supabase_configured():
        return await _upload_supabase(object_path, data, content_type)
    return _upload_local(object_path, data)
