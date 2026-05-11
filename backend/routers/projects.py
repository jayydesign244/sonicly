import os
import json
from fastapi import APIRouter, HTTPException, UploadFile, File, Depends
from fastapi.responses import StreamingResponse
from openai import AsyncOpenAI
from models.schemas import ProjectCreate, ProjectOut, ChatRequest, ExportRequest, ProcessingStatus
from auth import get_current_user
from datetime import datetime
from typing import List

router = APIRouter(prefix="/projects", tags=["projects"])

_projects: list[dict] = [
    {"id": 1, "name": "podcast_episode_12", "duration": "3:42", "status": "In Progress",
     "created_at": datetime.now(), "updated_at": datetime.now()},
    {"id": 2, "name": "interview_sarah_may", "duration": "18:04", "status": "Exported",
     "created_at": datetime.now(), "updated_at": datetime.now()},
    {"id": 3, "name": "webinar_recording_q2", "duration": "54:11", "status": "Exported",
     "created_at": datetime.now(), "updated_at": datetime.now()},
]
_next_id = 4

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


@router.get("/", response_model=List[ProjectOut])
async def list_projects(user: dict = Depends(get_current_user)):
    return [ProjectOut(**p) for p in _projects]


@router.post("/", response_model=ProjectOut, status_code=201)
async def create_project(payload: ProjectCreate, user: dict = Depends(get_current_user)):
    global _next_id
    project = {
        "id": _next_id,
        "name": payload.name,
        "duration": None,
        "status": "New",
        "created_at": datetime.now(),
        "updated_at": datetime.now(),
    }
    _projects.append(project)
    _next_id += 1
    return ProjectOut(**project)


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(project_id: int, user: dict = Depends(get_current_user)):
    project = next((p for p in _projects if p["id"] == project_id), None)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return ProjectOut(**project)


@router.delete("/{project_id}", status_code=204)
async def delete_project(project_id: int, user: dict = Depends(get_current_user)):
    global _projects
    _projects = [p for p in _projects if p["id"] != project_id]


@router.post("/{project_id}/upload")
async def upload_audio(
    project_id: int,
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
):
    project = next((p for p in _projects if p["id"] == project_id), None)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    project["status"] = "In Progress"
    project["updated_at"] = datetime.now()
    return {"message": "File uploaded successfully", "filename": file.filename}


@router.post("/{project_id}/chat")
async def chat(
    project_id: int,
    payload: ChatRequest,
    user: dict = Depends(get_current_user),
):
    project = next((p for p in _projects if p["id"] == project_id), None)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

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
async def processing_status(project_id: int, user: dict = Depends(get_current_user)):
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
):
    project = next((p for p in _projects if p["id"] == project_id), None)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    project["status"] = "Exported"
    project["updated_at"] = datetime.now()
    return {
        "message": "Export ready",
        "filename": f"{payload.filename}.{payload.format}",
        "size_mb": 8.4,
        "download_url": f"/downloads/{payload.filename}.{payload.format}",
    }
