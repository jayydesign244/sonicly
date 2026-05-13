"""Supabase Storage client (audio bucket) via the public REST API."""
import os
import re
import uuid
from typing import Optional

import httpx

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
BUCKET = os.environ.get("SUPABASE_BUCKET", "audio")


def is_configured() -> bool:
    return bool(SUPABASE_URL and SUPABASE_SERVICE_KEY)


def _headers(content_type: Optional[str] = None) -> dict:
    h = {
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "apikey": SUPABASE_SERVICE_KEY,
    }
    if content_type:
        h["Content-Type"] = content_type
        h["x-upsert"] = "true"
    return h


async def upload_audio(
    user_id: str,
    filename: str,
    data: bytes,
    content_type: str = "application/octet-stream",
) -> str:
    """Upload audio bytes; return the public URL."""
    if not is_configured():
        raise RuntimeError("Supabase storage not configured")

    # Strip path separators and anything that isn't a safe URL char
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", filename).strip("_") or "audio"
    object_path = f"{user_id}/{uuid.uuid4().hex}_{safe_name}"
    upload_url = f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{object_path}"

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            upload_url, content=data, headers=_headers(content_type)
        )
        resp.raise_for_status()

    return f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET}/{object_path}"
