import os
from dotenv import load_dotenv
load_dotenv()

from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from routers import projects
from auth import get_current_user, prefetch_jwks
from database import engine
from models.db import Base


@asynccontextmanager
async def lifespan(app):
    await prefetch_jwks()
    if engine is not None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    else:
        print("[db] DATABASE_URL not set — running without persistence")
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
