from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from models.schemas import ProjectCreate, ProjectOut, ChatRequest, ChatResponse, ExportRequest, ProcessingStatus
from datetime import datetime
from typing import List
import asyncio

router = APIRouter(prefix="/projects", tags=["projects"])

# In-memory store for prototype
_projects: list[dict] = [
    {"id": 1, "name": "podcast_episode_12", "duration": "3:42", "status": "In Progress",
     "created_at": datetime.now(), "updated_at": datetime.now()},
    {"id": 2, "name": "interview_sarah_may", "duration": "18:04", "status": "Exported",
     "created_at": datetime.now(), "updated_at": datetime.now()},
    {"id": 3, "name": "webinar_recording_q2", "duration": "54:11", "status": "Exported",
     "created_at": datetime.now(), "updated_at": datetime.now()},
]
_next_id = 4

AI_RESPONSES = [
    "Done! I've applied that change. Your audio sounds much cleaner now.",
    "Great choice! Removed that issue throughout the recording. Quality is now at 87.",
    "Done! Made that adjustment. Anything else you'd like to improve?",
    "Applied. The change is reflected in the waveform. Want me to do anything else?",
]
_response_idx = 0


@router.get("/", response_model=List[ProjectOut])
async def list_projects():
    return [ProjectOut(**p) for p in _projects]


@router.post("/", response_model=ProjectOut, status_code=201)
async def create_project(payload: ProjectCreate):
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
async def get_project(project_id: int):
    project = next((p for p in _projects if p["id"] == project_id), None)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return ProjectOut(**project)


@router.delete("/{project_id}", status_code=204)
async def delete_project(project_id: int):
    global _projects
    _projects = [p for p in _projects if p["id"] != project_id]


@router.post("/{project_id}/upload")
async def upload_audio(project_id: int, file: UploadFile = File(...)):
    project = next((p for p in _projects if p["id"] == project_id), None)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    project["status"] = "In Progress"
    project["updated_at"] = datetime.now()
    return {"message": "File uploaded successfully", "filename": file.filename}


@router.post("/{project_id}/chat", response_model=ChatResponse)
async def chat(project_id: int, payload: ChatRequest):
    global _response_idx
    await asyncio.sleep(0.3)  # Simulate processing
    response = AI_RESPONSES[_response_idx % len(AI_RESPONSES)]
    _response_idx += 1
    return ChatResponse(message=response, version_created=True)


@router.get("/{project_id}/processing", response_model=ProcessingStatus)
async def processing_status(project_id: int):
    return ProcessingStatus(
        project_id=project_id,
        step="transcribing",
        progress=0.75,
        complete=False,
    )


@router.post("/{project_id}/export")
async def export_project(project_id: int, payload: ExportRequest):
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
