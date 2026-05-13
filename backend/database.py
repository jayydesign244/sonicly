"""Async SQLAlchemy setup. Falls back to a local SQLite file for dev when
DATABASE_URL is missing, so the API can boot without Supabase configured."""
import os
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

DEV_SQLITE_URL = "sqlite+aiosqlite:///./sonicly_dev.db"


def _normalize_url(url: str) -> str:
    if not url:
        return ""
    # Supabase shows postgres:// or postgresql://; SQLAlchemy needs +asyncpg
    if url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url[len("postgres://") :]
    elif url.startswith("postgresql://") and "+asyncpg" not in url:
        url = "postgresql+asyncpg://" + url[len("postgresql://") :]
    return url


_raw = os.environ.get("DATABASE_URL", "")
DATABASE_URL = _normalize_url(_raw) or DEV_SQLITE_URL
IS_SQLITE = DATABASE_URL.startswith("sqlite")

if IS_SQLITE:
    engine = create_async_engine(DATABASE_URL, echo=False)
    print(f"[db] DATABASE_URL not set — using local SQLite at {DATABASE_URL}")
else:
    engine = create_async_engine(
        DATABASE_URL,
        echo=False,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
    )

SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
