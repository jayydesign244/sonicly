"""Clerk JWT verification for FastAPI."""
import os
import asyncio
from typing import Optional

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError

CLERK_ISSUER = os.environ.get("CLERK_ISSUER", "").rstrip("/")
CLERK_JWKS_URL = (
    os.environ.get("CLERK_JWKS_URL")
    or (f"{CLERK_ISSUER}/.well-known/jwks.json" if CLERK_ISSUER else "")
)

security = HTTPBearer(auto_error=False)

_jwks_cache: Optional[dict] = None
_jwks_lock = asyncio.Lock()


async def _jwks() -> dict:
    global _jwks_cache
    if _jwks_cache is not None:
        return _jwks_cache
    async with _jwks_lock:
        if _jwks_cache is not None:
            return _jwks_cache
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(CLERK_JWKS_URL)
            resp.raise_for_status()
            _jwks_cache = resp.json()
    return _jwks_cache


async def prefetch_jwks() -> None:
    """Call from app startup so the first user request doesn't pay the latency."""
    if CLERK_JWKS_URL:
        try:
            await _jwks()
        except Exception as exc:
            print(f"[auth] JWKS prefetch failed (will retry on first request): {exc}")


async def _key_for_kid(kid: str):
    keys = (await _jwks()).get("keys", [])
    return next((k for k in keys if k.get("kid") == kid), None)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """Verifies a Clerk-issued JWT and returns the decoded payload."""
    if not CLERK_JWKS_URL:
        return {"sub": "dev-user", "email": "dev@local"}

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    try:
        header = jwt.get_unverified_header(token)
        key = await _key_for_kid(header.get("kid"))
        if key is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unknown signing key",
            )
        payload = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            issuer=CLERK_ISSUER or None,
            options={"verify_aud": False},
        )
        return payload
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        )
