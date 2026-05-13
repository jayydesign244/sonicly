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


@asynccontextmanager
async def lifespan(app):
    await prefetch_jwks()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Lightweight in-place migrations for columns added after first deploy.
        # Postgres-only: SQLite either has it (fresh create_all) or doesn't
        # support ADD COLUMN IF NOT EXISTS on older versions.
        if not IS_SQLITE:
            await conn.execute(
                text("ALTER TABLE projects ADD COLUMN IF NOT EXISTS transcript JSONB")
            )
            await conn.execute(
                text("ALTER TABLE projects ADD COLUMN IF NOT EXISTS active_version_id INTEGER")
            )
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
