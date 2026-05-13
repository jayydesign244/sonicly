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
from services import audio_editor, fillers as fillers_service, voice as voice_service
from typing import List, Optional, Tuple

router = APIRouter(prefix="/projects", tags=["projects"])

OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "whisper-1")

_openai_client: Optional[AsyncOpenAI] = None


def _get_openai_client() -> AsyncOpenAI:
    """Lazy so the app can boot without OPENAI_API_KEY for non-AI endpoints."""
    global _openai_client
    if _openai_client is None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise HTTPException(
                status_code=503,
                detail="OPENAI_API_KEY not configured on the server",
            )
        _openai_client = AsyncOpenAI(api_key=api_key)
    return _openai_client

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
        result = await _get_openai_client().audio.transcriptions.create(
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
            stream = await _get_openai_client().chat.completions.create(
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


def _apply_edits_to_transcript(
    transcript: dict,
    deletes: List[Tuple[int, int]],
    replaces: List[Tuple[int, int, str]],
) -> dict:
    """Return a deep copy of the transcript with deletes stripped and
    replaces' word text overwritten. Word timestamps are kept (the
    audio splice keeps the timeline aligned at word boundaries)."""
    drop = {(s, w) for s, w in deletes}
    rmap = {(s, w): new for s, w, new in replaces}
    out = copy.deepcopy(transcript)
    for si, seg in enumerate(out.get("segments") or []):
        kept = []
        for wi, w in enumerate(seg.get("words") or []):
            if (si, wi) in drop:
                continue
            if (si, wi) in rmap:
                w = {**w, "text": rmap[(si, wi)]}
            kept.append(w)
        seg["words"] = kept
        seg["text"] = " ".join((w.get("text", "") or "").strip() for w in kept).strip()
    out["segments"] = [s for s in out["segments"] if s.get("words")]
    out["text"] = " ".join(s.get("text", "") for s in out["segments"]).strip()
    return out


def _word_range(transcript: dict, si: int, wi: int, pad: float = 0.04) -> Optional[Tuple[float, float]]:
    segs = (transcript or {}).get("segments") or []
    if si < 0 or si >= len(segs):
        return None
    words = segs[si].get("words") or []
    if wi < 0 or wi >= len(words):
        return None
    w = words[wi]
    try:
        return (max(0.0, float(w["start"]) - pad), float(w["end"]) + pad)
    except (KeyError, TypeError, ValueError):
        return None


async def _ensure_voice_clone(project: Project, source_audio: bytes) -> Tuple[str, bool]:
    """Return (voice_id, used_fallback). Clones the user's voice from the
    source audio; if the ElevenLabs plan doesn't include Instant Voice
    Cloning, falls back to a premade voice so the replace pipeline still
    works (with a clear "fallback voice" label on the resulting version).
    """
    if project.voice_id:
        return project.voice_id, project.voice_provider == voice_service.FALLBACK_VOICE_PROVIDER
    try:
        voice_id = await voice_service.clone_voice(
            source_audio, name=f"sonicly-{project.id}-{project.name[:32]}"
        )
        project.voice_id = voice_id
        project.voice_provider = "elevenlabs"
        return voice_id, False
    except voice_service.VoiceError as exc:
        if not exc.plan_upgrade_required:
            raise
        # Free-tier fallback: use a premade voice so the user can still
        # exercise the feature end-to-end. The version label will say so.
        project.voice_id = voice_service.FALLBACK_VOICE_ID
        project.voice_provider = voice_service.FALLBACK_VOICE_PROVIDER
        return voice_service.FALLBACK_VOICE_ID, True


@router.post("/{project_id}/voice/clone", response_model=ProjectOut)
async def clone_project_voice(
    project_id: int,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Clone the user's voice from the project's source audio. Idempotent —
    returns the existing voice_id when one is already attached."""
    project = await _get_owned_project(db, project_id, user)
    if project.voice_id:
        return ProjectOut.model_validate(project)
    if not project.audio_url:
        raise HTTPException(status_code=400, detail="Project has no audio to clone")
    if not voice_service.is_configured():
        raise HTTPException(
            status_code=503, detail="ELEVENLABS_API_KEY not configured"
        )

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(project.audio_url)
            resp.raise_for_status()
            audio_bytes = resp.content
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Fetch source audio: {exc}")

    try:
        _, used_fallback = await _ensure_voice_clone(project, audio_bytes)
    except voice_service.VoiceError as exc:
        if exc.plan_upgrade_required:
            raise HTTPException(
                status_code=402,
                detail=(
                    "ElevenLabs Instant Voice Cloning requires a paid plan "
                    "(Starter or higher). Upgrade at https://elevenlabs.io/pricing, "
                    "or proceed with a built-in voice — the Confirm flow will use "
                    "the premade voice automatically."
                ),
            )
        raise HTTPException(status_code=502, detail=str(exc))

    await db.commit()
    await db.refresh(project)
    return ProjectOut.model_validate(project)


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
        raise HTTPException(status_code=503, detail="ffmpeg not installed on the server")
    if not storage_configured():
        raise HTTPException(status_code=503, detail="Storage not configured")

    # Pick the source (parent version's URL if provided, else current).
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

    # Collect refs.
    delete_refs: List[Tuple[int, int]] = []
    replace_refs: List[Tuple[int, int, str]] = []
    for edit in payload.edits:
        t = edit.get("type")
        if t == "delete":
            delete_refs.extend(
                _resolve_word_refs(transcript=source_transcript, refs=edit.get("words", []))
            )
        elif t == "replace":
            w = edit.get("word", {})
            new_text = (edit.get("new_text") or "").strip()
            if not new_text:
                continue
            try:
                replace_refs.append((int(w["segment_idx"]), int(w["word_idx"]), new_text))
            except (KeyError, TypeError, ValueError):
                continue

    if not delete_refs and not replace_refs:
        raise HTTPException(status_code=400, detail="No edits to apply")

    if replace_refs and not voice_service.is_configured():
        raise HTTPException(
            status_code=503,
            detail="ELEVENLABS_API_KEY not configured (required for word replacement)",
        )

    with tempfile.TemporaryDirectory() as tmp:
        src_path = os.path.join(tmp, "in.mp3")
        out_path = os.path.join(tmp, "out.mp3")

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.get(source_url)
                resp.raise_for_status()
                src_bytes = resp.content
            with open(src_path, "wb") as f:
                f.write(src_bytes)
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Fetch source audio: {exc}")

        duration = await audio_editor.probe_duration(src_path)
        if duration <= 0:
            raise HTTPException(status_code=500, detail="Could not probe audio duration")

        # If we have replaces, ensure a voice clone is attached.
        used_fallback_voice = False
        if replace_refs:
            try:
                _, used_fallback_voice = await _ensure_voice_clone(project, src_bytes)
            except voice_service.VoiceError as exc:
                if exc.plan_upgrade_required:
                    raise HTTPException(
                        status_code=402,
                        detail=str(exc),
                    )
                raise HTTPException(status_code=502, detail=f"Voice clone: {exc}")

            # Generate one mp3 per replace, dump into the temp dir.
            for i, (si, wi, new_text) in enumerate(replace_refs):
                try:
                    audio = await voice_service.synthesize(project.voice_id, new_text)
                except voice_service.VoiceError as exc:
                    raise HTTPException(status_code=502, detail=f"TTS: {exc}")
                gen_path = os.path.join(tmp, f"gen_{i}.mp3")
                with open(gen_path, "wb") as f:
                    f.write(audio)
                replace_refs[i] = (si, wi, new_text, gen_path)  # type: ignore

        # Build chronological op list.
        events: List[dict] = []  # each: {start, end, type: 'delete'|'replace', path?}
        for si, wi in delete_refs:
            r = _word_range(source_transcript, si, wi)
            if r:
                events.append({"start": r[0], "end": r[1], "type": "delete"})
        for ref in replace_refs:
            if len(ref) < 4:
                continue  # safety
            si, wi, new_text, gen_path = ref  # type: ignore
            r = _word_range(source_transcript, si, wi, pad=0.0)
            if r:
                events.append({
                    "start": r[0], "end": r[1], "type": "replace", "path": gen_path
                })
        events.sort(key=lambda e: e["start"])

        # Convert events → ops (keep segments + replace inserts; deletes are gaps).
        ops: List[dict] = []
        cursor = 0.0
        for ev in events:
            if ev["start"] > cursor + 0.001:
                ops.append({"type": "keep", "start": cursor, "end": min(ev["start"], duration)})
            if ev["type"] == "replace":
                ops.append({"type": "insert", "path": ev["path"]})
            cursor = max(cursor, ev["end"])
        if cursor < duration - 0.001:
            ops.append({"type": "keep", "start": cursor, "end": duration})

        if not ops:
            raise HTTPException(status_code=400, detail="Edits would remove the entire audio")

        try:
            await audio_editor.render_with_ops(src_path, ops, out_path)
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

    new_transcript = _apply_edits_to_transcript(
        source_transcript,
        delete_refs,
        [(si, wi, new_text) for ref in replace_refs for si, wi, new_text, *_ in [ref]],
    )
    new_transcript["duration"] = new_duration

    parts = []
    if delete_refs:
        parts.append(f"Removed {len(delete_refs)}")
    if replace_refs:
        parts.append(f"Replaced {len(replace_refs)}")
    default_label = " · ".join(parts) + " word" + ("s" if (len(delete_refs) + len(replace_refs)) != 1 else "")
    if replace_refs and used_fallback_voice:
        default_label += " (premade voice)"

    version = AudioVersion(
        project_id=project_id,
        parent_id=payload.parent_version_id,
        label=payload.label or default_label,
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
