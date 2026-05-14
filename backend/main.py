import os
from dotenv import load_dotenv
load_dotenv()

from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from routers import projects
from auth import get_current_user, prefetch_jwks
from database import engine, IS_SQLITE
from models.db import Base
from storage import LOCAL_UPLOAD_DIR, LOCAL_PUBLIC_PREFIX, supabase_configured


async def _add_column_if_missing(conn, table: str, column: str, ddl_type: str):
    """Idempotent ADD COLUMN for both Postgres and SQLite.

    Postgres: ADD COLUMN IF NOT EXISTS (atomic).
    SQLite: tries ADD COLUMN and swallows the duplicate-column error.
    """
    if IS_SQLITE:
        try:
            await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}"))
        except Exception as exc:
            if "duplicate column" not in str(exc).lower():
                raise
    else:
        await conn.execute(
            text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {ddl_type}")
        )


@asynccontextmanager
async def lifespan(app):
    await prefetch_jwks()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Lightweight in-place migrations for columns added after first deploy.
        json_type = "JSON" if IS_SQLITE else "JSONB"
        await _add_column_if_missing(conn, "projects", "transcript", json_type)
        await _add_column_if_missing(conn, "projects", "active_version_id", "INTEGER")
        await _add_column_if_missing(conn, "projects", "voice_id", "VARCHAR(128)")
        await _add_column_if_missing(conn, "projects", "voice_provider", "VARCHAR(32)")
    yield

app = FastAPI(
    title="Sonicly API",
    description="AI Audio Editor — Backend API",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — allow Vercel frontend + local dev
allowed_origins = os.environ.get(
    "ALLOWED_ORIGINS",
    "http://localhost:3000,http://127.0.0.1:3000",
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in allowed_origins],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects.router, prefix="/api")

# Local audio storage fallback — mounted only when Supabase isn't configured.
if not supabase_configured():
    LOCAL_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    app.mount(
        LOCAL_PUBLIC_PREFIX,
        StaticFiles(directory=str(LOCAL_UPLOAD_DIR)),
        name="local-uploads",
    )
    print(f"[storage] Supabase not configured — serving uploads from {LOCAL_UPLOAD_DIR} at {LOCAL_PUBLIC_PREFIX}")


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "sonicly-api"}


@app.get("/api/me")
async def me(user: dict = Depends(get_current_user)):
    """Returns the authenticated Clerk user."""
    return {
        "id": user.get("sub"),
        "email": user.get("email") or user.get("email_address"),
        "name": user.get("name") or user.get("full_name"),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), reload=True)
