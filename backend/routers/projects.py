import copy
import io
import os
import json
import tempfile
import httpx
from fastapi import APIRouter, HTTPException, UploadFile, File, Depends
from fastapi.responses import StreamingResponse
from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from models.schemas import (
    ProjectCreate,
    ProjectOut,
    ChatRequest,
    ExportRequest,
    ProcessingStatus,
    ApplyEditsRequest,
    AudioVersionOut,
    FillersResponse,
    WordRef,
)
from models.db import Project, AudioVersion
from auth import get_current_user
from database import get_db
from storage import upload_audio as storage_upload, is_configured as storage_configured
from services import audio_editor, fillers as fillers_service
from typing import List, Tuple

router = APIRouter(prefix="/projects", tags=["projects"])

openai_client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "whisper-1")

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


def _filename_from_url(url: str) -> str:
    name = url.rsplit("/", 1)[-1].split("?", 1)[0] or "audio.bin"
    # Whisper picks the decoder from the extension — guarantee one it accepts.
    if "." not in name:
        name += ".mp3"
    return name


def _build_transcript(whisper_response: dict) -> dict:
    """Reshape Whisper's verbose_json into our segments+words structure.

    Whisper returns top-level `segments` (no per-word timing) and a flat
    `words` list with timing. We assign each word to the segment whose
    [start, end] window contains its midpoint, so the UI can render lines
    while still having word-level click-to-seek.
    """
    raw_segments = whisper_response.get("segments") or []
    raw_words = whisper_response.get("words") or []

    segments = [
        {
            "start": float(s.get("start", 0.0)),
            "end": float(s.get("end", 0.0)),
            "text": (s.get("text") or "").strip(),
            "words": [],
        }
        for s in raw_segments
    ]

    if not segments and raw_words:
        # No segments — fall back to a single segment spanning the whole audio.
        segments = [{
            "start": float(raw_words[0].get("start", 0.0)),
            "end": float(raw_words[-1].get("end", 0.0)),
            "text": (whisper_response.get("text") or "").strip(),
            "words": [],
        }]

    for w in raw_words:
        start = float(w.get("start", 0.0))
        end = float(w.get("end", start))
        mid = (start + end) / 2
        target = next(
            (s for s in segments if s["start"] <= mid <= s["end"]),
            segments[-1] if segments else None,
        )
        if target is not None:
            target["words"].append({
                "text": w.get("word", ""),
                "start": start,
                "end": end,
            })

    return {
        "language": whisper_response.get("language"),
        "duration": whisper_response.get("duration"),
        "text": whisper_response.get("text", ""),
        "segments": segments,
    }


@router.post("/{project_id}/transcribe", response_model=ProjectOut)
async def transcribe_project(
    project_id: int,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await _get_owned_project(db, project_id, user)
    if not project.audio_url:
        raise HTTPException(status_code=400, detail="Project has no uploaded audio")
    if not os.environ.get("OPENAI_API_KEY"):
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY not configured")

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(project.audio_url)
            resp.raise_for_status()
            audio_bytes = resp.content
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Could not fetch audio: {exc}")

    filename = _filename_from_url(project.audio_url)
    audio_buf = io.BytesIO(audio_bytes)
    audio_buf.name = filename

    try:
        result = await openai_client.audio.transcriptions.create(
            model=WHISPER_MODEL,
            file=audio_buf,
            response_format="verbose_json",
            timestamp_granularities=["word", "segment"],
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Transcription failed: {exc}")

    transcript = _build_transcript(
        result.model_dump() if hasattr(result, "model_dump") else dict(result)
    )

    project.transcript = transcript
    flag_modified(project, "transcript")
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


# ─── Transcript-driven editing ────────────────────────────────────────


@router.post("/{project_id}/fillers", response_model=FillersResponse)
async def detect_fillers(
    project_id: int,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await _get_owned_project(db, project_id, user)
    if not project.transcript:
        raise HTTPException(status_code=400, detail="Project has no transcript yet")
    refs = fillers_service.find_fillers(project.transcript)
    return FillersResponse(
        fillers=[WordRef(segment_idx=s, word_idx=w) for s, w in refs],
        total=len(refs),
    )


@router.get("/{project_id}/versions", response_model=List[AudioVersionOut])
async def list_versions(
    project_id: int,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_owned_project(db, project_id, user)
    result = await db.execute(
        select(AudioVersion)
        .where(AudioVersion.project_id == project_id)
        .order_by(AudioVersion.created_at.asc())
    )
    return [AudioVersionOut.model_validate(v) for v in result.scalars()]


@router.post(
    "/{project_id}/versions/{version_id}/activate", response_model=ProjectOut
)
async def activate_version(
    project_id: int,
    version_id: int,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await _get_owned_project(db, project_id, user)
    result = await db.execute(
        select(AudioVersion).where(
            AudioVersion.id == version_id,
            AudioVersion.project_id == project_id,
        )
    )
    version = result.scalar_one_or_none()
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")

    project.active_version_id = version.id
    project.audio_url = version.audio_url
    if version.transcript:
        project.transcript = version.transcript
        flag_modified(project, "transcript")
    await db.commit()
    await db.refresh(project)
    return ProjectOut.model_validate(project)


def _resolve_word_refs(
    transcript: dict, refs: List[dict]
) -> List[Tuple[int, int]]:
    out: List[Tuple[int, int]] = []
    for r in refs:
        try:
            out.append((int(r["segment_idx"]), int(r["word_idx"])))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _transcript_minus_words(
    transcript: dict, removed: List[Tuple[int, int]]
) -> dict:
    """Return a deep copy of the transcript with the given words stripped."""
    drop = {(s, w) for s, w in removed}
    out = copy.deepcopy(transcript)
    for si, seg in enumerate(out.get("segments") or []):
        kept = [w for wi, w in enumerate(seg.get("words") or []) if (si, wi) not in drop]
        seg["words"] = kept
        seg["text"] = " ".join(w.get("text", "").strip() for w in kept).strip()
    # Drop empty segments — common after a full-line delete.
    out["segments"] = [s for s in out["segments"] if s.get("words")]
    out["text"] = " ".join(s.get("text", "") for s in out["segments"]).strip()
    return out


@router.post("/{project_id}/edits/apply", response_model=AudioVersionOut)
async def apply_edits(
    project_id: int,
    payload: ApplyEditsRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await _get_owned_project(db, project_id, user)
    if not project.audio_url:
        raise HTTPException(status_code=400, detail="Project has no audio")
    if not project.transcript:
        raise HTTPException(status_code=400, detail="Project has no transcript")
    if not audio_editor.ffmpeg_available():
        raise HTTPException(
            status_code=503,
            detail="ffmpeg not installed on the server",
        )
    if not storage_configured():
        raise HTTPException(status_code=503, detail="Storage not configured")

    # Pick the source audio (parent version's URL if provided, else current).
    source_url = project.audio_url
    source_transcript = project.transcript
    if payload.parent_version_id is not None:
        result = await db.execute(
            select(AudioVersion).where(
                AudioVersion.id == payload.parent_version_id,
                AudioVersion.project_id == project_id,
            )
        )
        parent = result.scalar_one_or_none()
        if parent:
            source_url = parent.audio_url
            source_transcript = parent.transcript or source_transcript

    # Collect deletion word refs from all delete-typed edits.
    delete_refs: List[Tuple[int, int]] = []
    for edit in payload.edits:
        if edit.get("type") == "delete":
            delete_refs.extend(_resolve_word_refs(transcript=source_transcript, refs=edit.get("words", [])))
        # "replace" edits are no-ops here until the voice service lands.

    if not delete_refs:
        raise HTTPException(
            status_code=400,
            detail="No supported edits in this request (only delete is implemented)",
        )

    ranges = fillers_service.words_to_ranges(source_transcript, delete_refs)

    with tempfile.TemporaryDirectory() as tmp:
        src_path = os.path.join(tmp, "in.mp3")
        out_path = os.path.join(tmp, "out.mp3")

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.get(source_url)
                resp.raise_for_status()
                with open(src_path, "wb") as f:
                    f.write(resp.content)
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Fetch source audio: {exc}")

        duration = await audio_editor.probe_duration(src_path)
        keeps = audio_editor.keep_ranges(ranges, duration)
        if not keeps:
            raise HTTPException(
                status_code=400,
                detail="Edits would remove the entire audio",
            )

        try:
            await audio_editor.render_with_keeps(src_path, keeps, out_path)
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc))

        with open(out_path, "rb") as f:
            rendered = f.read()
        new_duration = await audio_editor.probe_duration(out_path)

    # Persist new file → storage → version row.
    try:
        public_url = await storage_upload(
            user_id=_user_id(user),
            filename=f"edit_{project_id}.mp3",
            data=rendered,
            content_type="audio/mpeg",
        )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Upload edited audio: {exc}")

    new_transcript = _transcript_minus_words(source_transcript, delete_refs)
    new_transcript["duration"] = new_duration

    version = AudioVersion(
        project_id=project_id,
        parent_id=payload.parent_version_id,
        label=payload.label or f"Removed {len(delete_refs)} word{'s' if len(delete_refs) != 1 else ''}",
        audio_url=public_url,
        transcript=new_transcript,
        duration=new_duration,
    )
    db.add(version)
    await db.flush()

    project.audio_url = public_url
    project.transcript = new_transcript
    project.active_version_id = version.id
    flag_modified(project, "transcript")
    await db.commit()
    await db.refresh(version)
    return AudioVersionOut.model_validate(version)
