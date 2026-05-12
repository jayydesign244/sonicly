import os
import json
import httpx
from fastapi import APIRouter, HTTPException, UploadFile, File, Depends
from fastapi.responses import StreamingResponse
from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.schemas import (
    ProjectCreate,
    ProjectOut,
    ChatRequest,
    ExportRequest,
    ProcessingStatus,
)
from models.db import Project
from auth import get_current_user
from database import get_db
from storage import upload_audio as storage_upload, is_configured as storage_configured
from typing import List

router = APIRouter(prefix="/projects", tags=["projects"])

openai_client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

SYSTEM_PROMPT = (
    "You are Sonicly, an AI audio editing assistant inside a web app. "
    "The user is editing an audio recording (podcast, interview, voiceover). "
    "Help them with: noise reduction, removing filler words (um, uh, like), "
    "leveling volume, trimming silence, EQ/warmth adjustments, de-essing, and reverb. "
    "Be concise and conversational. When the user asks for an edit, confirm what "
    "you've applied in 1-2 sentences. If the user is unclear, ask one short follow-up."
)


def _user_id(user: dict) -> str:
    return user.get("sub") or "anonymous"


async def _get_owned_project(
    db: AsyncSession, project_id: int, user: dict
) -> Project:
    result = await db.execute(
        select(Project).where(
            Project.id == project_id, Project.user_id == _user_id(user)
        )
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.get("/", response_model=List[ProjectOut])
async def list_projects(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Project)
        .where(Project.user_id == _user_id(user))
        .order_by(Project.updated_at.desc())
    )
    return [ProjectOut.model_validate(p) for p in result.scalars()]


@router.post("/", response_model=ProjectOut, status_code=201)
async def create_project(
    payload: ProjectCreate,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = Project(
        user_id=_user_id(user),
        name=payload.name,
        duration=payload.duration,
        status="New",
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return ProjectOut.model_validate(project)


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(
    project_id: int,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await _get_owned_project(db, project_id, user)
    return ProjectOut.model_validate(project)


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: int,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await _get_owned_project(db, project_id, user)
    await db.delete(project)
    await db.commit()


@router.post("/{project_id}/upload", response_model=ProjectOut)
async def upload_audio(
    project_id: int,
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await _get_owned_project(db, project_id, user)

    if not storage_configured():
        raise HTTPException(
            status_code=503,
            detail="Storage not configured (SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY)",
        )

    data = await file.read()
    try:
        public_url = await storage_upload(
            user_id=_user_id(user),
            filename=file.filename or "audio.bin",
            data=data,
            content_type=file.content_type or "application/octet-stream",
        )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Upload failed: {exc}")

    project.audio_url = public_url
    project.status = "In Progress"
    await db.commit()
    await db.refresh(project)
    return ProjectOut.model_validate(project)


@router.post("/{project_id}/chat")
async def chat(
    project_id: int,
    payload: ChatRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_owned_project(db, project_id, user)

    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + [
        {"role": m.role, "content": m.content} for m in payload.messages
    ]

    async def event_generator():
        try:
            stream = await openai_client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=messages,
                stream=True,
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta.content if chunk.choices else None
                if delta:
                    yield f"data: {json.dumps({'delta': delta})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/{project_id}/processing", response_model=ProcessingStatus)
async def processing_status(
    project_id: int,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_owned_project(db, project_id, user)
    return ProcessingStatus(
        project_id=project_id,
        step="transcribing",
        progress=0.75,
        complete=False,
    )


@router.post("/{project_id}/export")
async def export_project(
    project_id: int,
    payload: ExportRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await _get_owned_project(db, project_id, user)
    project.status = "Exported"
    await db.commit()
    return {
        "message": "Export ready",
        "filename": f"{payload.filename}.{payload.format}",
        "size_mb": 8.4,
        "download_url": f"/downloads/{payload.filename}.{payload.format}",
    }
