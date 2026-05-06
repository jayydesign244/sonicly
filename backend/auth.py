"""Clerk JWT verification for FastAPI."""
import os
from functools import lru_cache

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


@lru_cache(maxsize=1)
def _jwks() -> dict:
    resp = httpx.get(CLERK_JWKS_URL, timeout=5.0)
    resp.raise_for_status()
    return resp.json()


def _key_for_kid(kid: str):
    keys = _jwks().get("keys", [])
    return next((k for k in keys if k.get("kid") == kid), None)


def get_current_user(
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
        key = _key_for_kid(header.get("kid"))
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
