import copy
import io
import os
import json
import re
import shutil
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
    ExportResult,
    ProcessingStatus,
    ApplyEditsRequest,
    ApplyOperationRequest,
    DeleteRangeRequest,
    AudioVersionOut,
    FillersResponse,
    WordRef,
)
from models.db import Project, AudioVersion
from auth import get_current_user
from database import get_db, SessionLocal
from storage import upload_audio as storage_upload, is_configured as storage_configured
from services import audio_editor, fillers as fillers_service, voice as voice_service, intent as intent_service
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
    "You are Sonicly, an AI audio editor running inside a real web app. "
    "You CAN edit audio — not just give advice. A separate intent parser "
    "handles structured edit commands and executes them before you ever "
    "see the message. The user sees the result reflected in the editor."
    "\n\n"
    "Capabilities the system already executes via chat:\n"
    "  • Delete a specific time range (e.g. 'remove 0:16 to 1:22', "
    "'delete the first 20 seconds').\n"
    "  • Voice: VOICE_DEEPER (1–4 semitones), VOICE_BRIGHTER (1–3 semitones).\n"
    "  • Loudness: NORMALISE_LOUDNESS (podcast -16 / YouTube -14), "
    "ADJUST_VOLUME up/down by N dB, BALANCE_SPEAKERS.\n"
    "  • Cleanup: REMOVE_HUM, REMOVE_BREATHS, TRIM_SILENCE.\n"
    "Filler-word removal and word-level transcript edits live behind "
    "dedicated buttons; mention them when relevant.\n\n"
    "When you reply:\n"
    "1. NEVER tell the user to 'use the designated button' for things "
    "above — they ARE executed from chat. "
    "2. If a previous turn proposed an edit and the user says 'yes/apply/"
    "do it', that's a confirmation — the parser will re-emit it as a "
    "structured action automatically; you don't need to apologise.\n"
    "3. If they ask for something needing details you don't have "
    "(e.g. 'remove the boring part'), ask one short clarifying question.\n"
    "4. Stay concise — one or two short sentences. Match the user's language."
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


_CT_TO_EXT = {
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/wave": "wav",
    "audio/mp4": "m4a",
    "audio/x-m4a": "m4a",
    "audio/aac": "aac",
    "audio/ogg": "ogg",
    "audio/webm": "webm",
    "audio/flac": "flac",
    "audio/x-flac": "flac",
    "video/mp4": "mp4",
    "video/webm": "webm",
}

# Whisper's accepted set, per OpenAI docs.
_WHISPER_EXTS = {"mp3", "mp4", "mpeg", "mpga", "m4a", "wav", "webm", "flac", "ogg"}


def _ext_from_content_type(content_type: Optional[str]) -> Optional[str]:
    if not content_type:
        return None
    base = content_type.split(";", 1)[0].strip().lower()
    return _CT_TO_EXT.get(base)


def _filename_from_url(url: str, content_type: Optional[str] = None) -> str:
    """Build a filename Whisper can decode.

    Strategy: take the basename from the URL; if its extension isn't in
    Whisper's accepted set, override it using the response's Content-Type
    (e.g. audio/webm → .webm). Only fall back to .mp3 when neither the
    URL nor the content type tells us anything useful — that path is the
    risky one, so we want to avoid it whenever possible.
    """
    name = url.rsplit("/", 1)[-1].split("?", 1)[0] or "audio"
    stem, dot, ext = name.rpartition(".")
    ext = ext.lower() if dot else ""

    if ext in _WHISPER_EXTS:
        return name

    ct_ext = _ext_from_content_type(content_type)
    if ct_ext and ct_ext in _WHISPER_EXTS:
        base = stem if dot else name
        return f"{base}.{ct_ext}"

    return f"{stem if dot else name}.mp3"


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
    """Transcribe the project audio with Whisper.

    Strategy for handling Whisper's 25 MB per-request cap:
      1. Download the source.
      2. audio_editor.prepare_for_whisper compresses to mono 24 kbps Opus,
         which is small enough for ~2 hours in one piece.
      3. If even compressed the file is still too big, it gets chunked into
         ~10 min pieces. We transcribe each chunk, offset its timestamps,
         and merge into one transcript.
    The user's original audio_url is never modified — compression is only
    for the Whisper call.
    """
    project = await _get_owned_project(db, project_id, user)
    if not project.audio_url:
        raise HTTPException(status_code=400, detail="Project has no uploaded audio")
    if not os.environ.get("OPENAI_API_KEY"):
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY not configured")
    if not audio_editor.ffmpeg_available():
        raise HTTPException(status_code=503, detail="ffmpeg not installed on the server")

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.get(project.audio_url)
            resp.raise_for_status()
            audio_bytes = resp.content
            content_type = resp.headers.get("content-type")
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Could not fetch audio: {exc}")

    filename = _filename_from_url(project.audio_url, content_type)
    source_ext = os.path.splitext(filename)[1] or ".mp3"

    with tempfile.TemporaryDirectory() as work_dir:
        src_path = os.path.join(work_dir, f"source{source_ext}")
        with open(src_path, "wb") as f:
            f.write(audio_bytes)

        try:
            pieces = await audio_editor.prepare_for_whisper(src_path, work_dir)
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=f"Audio preprocessing failed: {exc}")

        client_ai = _get_openai_client()
        merged_segments: List[dict] = []
        merged_words: List[dict] = []
        text_parts: List[str] = []
        detected_language: Optional[str] = None
        total_duration = 0.0

        for piece_path, offset in pieces:
            with open(piece_path, "rb") as f:
                piece_bytes = f.read()
            buf = io.BytesIO(piece_bytes)
            buf.name = os.path.basename(piece_path)

            try:
                result = await client_ai.audio.transcriptions.create(
                    model=WHISPER_MODEL,
                    file=buf,
                    response_format="verbose_json",
                    timestamp_granularities=["word", "segment"],
                )
            except Exception as exc:
                raise HTTPException(
                    status_code=502,
                    detail=f"Transcription failed (chunk @ {offset:.0f}s): {exc}",
                )

            raw = result.model_dump() if hasattr(result, "model_dump") else dict(result)

            # Offset all timestamps so chunks line up on the original timeline.
            for s in raw.get("segments") or []:
                s["start"] = float(s.get("start", 0.0)) + offset
                s["end"] = float(s.get("end", 0.0)) + offset
                merged_segments.append(s)
            for w in raw.get("words") or []:
                w["start"] = float(w.get("start", 0.0)) + offset
                w["end"] = float(w.get("end", 0.0)) + offset
                merged_words.append(w)

            piece_text = (raw.get("text") or "").strip()
            if piece_text:
                text_parts.append(piece_text)
            detected_language = detected_language or raw.get("language")
            piece_duration = float(raw.get("duration") or 0.0)
            total_duration = max(total_duration, offset + piece_duration)

    merged_response = {
        "language": detected_language,
        "duration": total_duration,
        "text": " ".join(text_parts),
        "segments": merged_segments,
        "words": merged_words,
    }
    transcript = _build_transcript(merged_response)

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
    """Stream a chat reply, executing any audio edit the user requests.

    Flow:
      1. Take the latest user message and ask the intent parser whether
         it's a structured action (e.g. delete a time range) or just chat.
      2. If it's an action, execute it server-side, create a new
         AudioVersion, then emit:
           data: {"delta": "...reply text..."}
           data: {"action": {"type": "delete_range", "version_id": N, ...}}
           data: {"done": true}
         The client uses the "action" event to reload audio + transcript.
      3. If it's chat, stream a normal GPT reply.
    """
    project = await _get_owned_project(db, project_id, user)

    last_user_message: Optional[str] = next(
        (m.content for m in reversed(payload.messages) if m.role == "user"),
        None,
    )
    chat_history = [{"role": m.role, "content": m.content} for m in payload.messages]
    # History EXCLUDING the latest user message — the parser sees it
    # separately so follow-ups like "yes apply" can be resolved against
    # what the assistant previously proposed.
    prior_history = chat_history[:-1] if chat_history and chat_history[-1]["role"] == "user" else chat_history
    client_ai = _get_openai_client()

    # First: try to classify the user's last message as a structured action.
    parsed: Optional[dict] = None
    if last_user_message:
        try:
            parsed = await intent_service.extract_intent(
                client_ai, last_user_message, history=prior_history
            )
        except Exception:
            # Intent parser is best-effort. Fall back to plain chat on any error.
            parsed = None

    async def event_generator():
        try:
            ops = (parsed or {}).get("operations") or []
            parser_reply = (parsed or {}).get("reply") or ""
            suggestions = (parsed or {}).get("suggestions")

            # ---- No structured ops: chat-only path ------------------------
            if not ops:
                # Trust the intent parser's reply when it gave one (it
                # already knows the user's language and intent). Only
                # fall back to streaming a fresh GPT chat if the parser
                # didn't produce a reply for some reason.
                if parser_reply:
                    yield f"data: {json.dumps({'delta': parser_reply})}\n\n"
                else:
                    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + chat_history
                    stream = await client_ai.chat.completions.create(
                        model=OPENAI_MODEL,
                        messages=messages,
                        stream=True,
                    )
                    async for chunk in stream:
                        delta = chunk.choices[0].delta.content if chunk.choices else None
                        if delta:
                            yield f"data: {json.dumps({'delta': delta})}\n\n"
                if suggestions:
                    yield f"data: {json.dumps({'suggestions': suggestions})}\n\n"
                yield f"data: {json.dumps({'done': True})}\n\n"
                return

            # ---- Multi-op pipeline ----------------------------------------
            # FastAPI closes the injected `db` session as soon as this
            # streaming handler returns, which races with the writes we'd
            # do inside the generator. Open a fresh session whose lifetime
            # we control end-to-end.
            try:
                async with SessionLocal() as edit_db:
                    edit_project = await _get_owned_project(
                        edit_db, project_id, user
                    )
                    version, executed_types = await _run_op_pipeline(
                        db=edit_db,
                        project=edit_project,
                        user=user,
                        ops=ops,
                    )
                    version_payload = {
                        "type": "pipeline",
                        "operations": executed_types,
                        "version_id": version.id,
                        "audio_url": version.audio_url,
                    }
            except HTTPException as exc:
                yield f"data: {json.dumps({'delta': f'⚠️ {exc.detail}'})}\n\n"
                yield f"data: {json.dumps({'done': True})}\n\n"
                return

            reply = parser_reply or "Done."
            yield f"data: {json.dumps({'delta': reply})}\n\n"
            yield f"data: {json.dumps({'action': version_payload})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


async def _execute_apply_operation(
    *,
    db: AsyncSession,
    project: Project,
    user: dict,
    op_type: str,
    op_params: dict,
) -> AudioVersion:
    """Apply a Phase-A FFmpeg primitive (hum/loudness/pitch/etc.) and create
    a new AudioVersion. Mirrors the apply_operation HTTP endpoint but runs
    in-process so the chat handler can call it directly."""
    if not project.audio_url:
        raise HTTPException(status_code=400, detail="Project has no audio")
    if not audio_editor.ffmpeg_available():
        raise HTTPException(status_code=503, detail="ffmpeg not installed on the server")
    if not storage_configured():
        raise HTTPException(status_code=503, detail="Storage not configured")

    op_type_norm = (op_type or "").upper()
    # Single-pass FFmpeg only. The multi-op pipeline in /chat handles
    # API ops, transcript ops, and meta pipelines.
    if op_type_norm not in audio_editor.FFMPEG_OPERATIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported operation: {op_type}",
        )
    try:
        audio_filter, default_label = audio_editor.build_operation_filter(
            op_type_norm, op_params or {}
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    source_url = project.audio_url
    source_transcript = project.transcript

    with tempfile.TemporaryDirectory() as tmp:
        src_path = os.path.join(tmp, "in.mp3")
        out_path = os.path.join(tmp, "out.mp3")

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.get(source_url)
                resp.raise_for_status()
                with open(src_path, "wb") as f:
                    f.write(resp.content)
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Fetch source audio: {exc}")

        try:
            await audio_editor.apply_audio_filter(src_path, out_path, audio_filter)
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc))

        with open(out_path, "rb") as f:
            rendered = f.read()
        new_duration = await audio_editor.probe_duration(out_path)

    try:
        public_url = await storage_upload(
            user_id=_user_id(user),
            filename=f"chat_op_{op_type_norm.lower()}_{project.id}.mp3",
            data=rendered,
            content_type="audio/mpeg",
        )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Upload processed audio: {exc}")

    # FFmpeg filters that change duration (TRIM_SILENCE) shift transcript
    # timestamps too. For everything else duration is unchanged. We carry
    # the source transcript through and just update the duration field — a
    # proper retranscription on duration-changing ops can be a follow-up.
    new_transcript = copy.deepcopy(source_transcript) if source_transcript else None
    if new_transcript is not None:
        new_transcript["duration"] = new_duration

    version = AudioVersion(
        project_id=project.id,
        parent_id=project.active_version_id,
        label=default_label,
        audio_url=public_url,
        transcript=new_transcript,
        duration=new_duration,
    )
    db.add(version)
    await db.flush()

    project.audio_url = public_url
    project.transcript = new_transcript
    project.active_version_id = version.id
    if new_transcript is not None:
        flag_modified(project, "transcript")
    await db.commit()
    await db.refresh(version)
    return version


async def _execute_delete_range(
    *,
    db: AsyncSession,
    project: Project,
    user: dict,
    start: float,
    end: float,
) -> AudioVersion:
    """Same machinery as the /operations/delete-range endpoint, callable
    in-process from the chat handler. Raises HTTPException on any failure
    so the chat stream can surface a clean error."""
    if not project.audio_url:
        raise HTTPException(status_code=400, detail="Project has no audio")
    if not audio_editor.ffmpeg_available():
        raise HTTPException(status_code=503, detail="ffmpeg not installed on the server")
    if not storage_configured():
        raise HTTPException(status_code=503, detail="Storage not configured")

    start = max(0.0, float(start))
    end = float(end)
    if end <= start:
        raise HTTPException(status_code=400, detail="end must be greater than start")

    source_url = project.audio_url
    source_transcript = project.transcript

    with tempfile.TemporaryDirectory() as tmp:
        src_path = os.path.join(tmp, "in.mp3")
        out_path = os.path.join(tmp, "out.mp3")

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.get(source_url)
                resp.raise_for_status()
                with open(src_path, "wb") as f:
                    f.write(resp.content)
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Fetch source audio: {exc}")

        duration = await audio_editor.probe_duration(src_path)
        if duration <= 0:
            raise HTTPException(status_code=500, detail="Could not probe audio duration")
        end = min(end, duration)
        if end <= start:
            raise HTTPException(
                status_code=400,
                detail=f"That range is outside the {duration:.0f}s audio",
            )

        keeps = audio_editor.keep_ranges([(start, end)], duration)
        if not keeps:
            raise HTTPException(
                status_code=400,
                detail="Deleting that range would remove the entire audio",
            )

        try:
            await audio_editor.render_with_keeps(src_path, keeps, out_path)
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc))

        with open(out_path, "rb") as f:
            rendered = f.read()
        new_duration = await audio_editor.probe_duration(out_path)

    try:
        public_url = await storage_upload(
            user_id=_user_id(user),
            filename=f"chat_cut_{project.id}.mp3",
            data=rendered,
            content_type="audio/mpeg",
        )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Upload processed audio: {exc}")

    new_transcript = _shift_transcript_after_delete(source_transcript, start, end)
    if new_transcript is not None:
        new_transcript["duration"] = new_duration

    def _fmt(t: float) -> str:
        m, s = divmod(int(t), 60)
        return f"{m}:{s:02d}"

    version = AudioVersion(
        project_id=project.id,
        parent_id=project.active_version_id,
        label=f"Removed {_fmt(start)}–{_fmt(end)}",
        audio_url=public_url,
        transcript=new_transcript,
        duration=new_duration,
    )
    db.add(version)
    await db.flush()

    project.audio_url = public_url
    project.transcript = new_transcript
    project.active_version_id = version.id
    if new_transcript is not None:
        flag_modified(project, "transcript")
    await db.commit()
    await db.refresh(version)
    return version


# ---- Multi-op chat pipeline ------------------------------------------------
# Canonical processing order from audio_processing_map.md SECTION 5. Lower
# numbers run earlier. Ops without an explicit order land at the default 50.
_OP_ORDER = {
    "NOISE_REMOVAL":       10,
    "REMOVE_REVERB":       10,
    "NOISE_GATE":          20,
    "REMOVE_HUM":          30,
    "REMOVE_WIND":         30,
    "REMOVE_PLOSIVES":     30,
    "REMOVE_MOUTH_SOUNDS": 30,
    "REMOVE_FILLERS":      40,
    "TRIM_SILENCE":        42,
    "delete_range":        45,
    "REMOVE_BREATHS":      50,
    "FIX_MUDDY":           60,
    "FIX_TINNY":           60,
    "FIX_BOXY":            60,
    "FIX_NASAL":           60,
    "REDUCE_BASS":         60,
    "REDUCE_AIR":          60,
    "VOICE_WARMER":        65,
    "VOICE_BRIGHTER":      65,
    "ADD_PRESENCE":        65,
    "ADD_AIR":             65,
    "ADD_BASS":            65,
    "REMOVE_SIBILANCE":    70,   # de-ess after EQ
    "BALANCE_SPEAKERS":    75,
    "COMPRESS_DYNAMICS":   80,
    "VOICE_DEEPER":        85,
    "ADJUST_VOLUME":       90,
    "NORMALISE_LOUDNESS":  95,
    "VOICE_PODCAST":       95,   # preset, late stage
    "VOICE_RADIO":         95,
    "LIMIT_PEAKS":         99,
}


def _op_sort_key(op: dict) -> int:
    if op.get("kind") == "delete_range":
        return _OP_ORDER.get("delete_range", 50)
    return _OP_ORDER.get(op.get("type") or "", 50)


def _expand_meta_ops(ops: List[dict]) -> List[dict]:
    """Expand meta operations (FULL_CLEANUP, VOICE_AUTHORITATIVE) into the
    fixed sub-operation lists declared in audio_editor.META_OPERATIONS."""
    expanded: List[dict] = []
    for op in ops:
        if op.get("kind") == "apply_operation":
            t = op.get("type")
            if t in audio_editor.META_OPERATIONS:
                for sub_type, sub_params in audio_editor.META_OPERATIONS[t]:
                    expanded.append({
                        "kind": "apply_operation",
                        "type": sub_type,
                        "params": dict(sub_params or {}),
                    })
                continue
        expanded.append(op)
    return expanded


def _fmt_mmss(t: float) -> str:
    m, s = divmod(int(t), 60)
    return f"{m}:{s:02d}"


async def _run_op_pipeline(
    *,
    db: AsyncSession,
    project: Project,
    user: dict,
    ops: List[dict],
) -> Tuple[AudioVersion, List[str]]:
    """Execute a chain of ops on the project audio, producing one new
    AudioVersion. Returns (version, executed_op_types).

    The pipeline walks ops in canonical processing order on a working
    file, hopping from one temp file to the next per op:
      • FFmpeg ops          -> audio_editor.apply_audio_filter
      • API ops (NOISE/REVERB) -> voice.audio_isolate
      • REMOVE_FILLERS      -> fillers_service.find_fillers + render_with_keeps
      • delete_range        -> render_with_keeps with the inverted range
    Meta ops (FULL_CLEANUP, VOICE_AUTHORITATIVE) are expanded first.
    """
    if not project.audio_url:
        raise HTTPException(status_code=400, detail="Project has no audio")
    if not audio_editor.ffmpeg_available():
        raise HTTPException(status_code=503, detail="ffmpeg not installed on the server")
    if not storage_configured():
        raise HTTPException(status_code=503, detail="Storage not configured")

    ordered = sorted(_expand_meta_ops(ops), key=_op_sort_key)
    if not ordered:
        raise HTTPException(status_code=400, detail="No executable operations")

    executed_types: List[str] = []
    labels: List[str] = []

    with tempfile.TemporaryDirectory() as tmp:
        src_path = os.path.join(tmp, "src.mp3")
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.get(project.audio_url)
                resp.raise_for_status()
                with open(src_path, "wb") as f:
                    f.write(resp.content)
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Fetch source audio: {exc}")

        current_path = src_path
        current_transcript = project.transcript

        for i, op in enumerate(ordered):
            next_path = os.path.join(tmp, f"step_{i:02d}.mp3")
            kind = op.get("kind")

            # ---- delete_range ---------------------------------------------
            if kind == "delete_range":
                start = max(0.0, float(op["start_seconds"]))
                end = float(op["end_seconds"])
                duration = await audio_editor.probe_duration(current_path)
                if duration <= 0:
                    raise HTTPException(status_code=500, detail="Could not probe audio duration")
                end = min(end, duration)
                if end <= start:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Range outside the {duration:.0f}s audio",
                    )
                keeps = audio_editor.keep_ranges([(start, end)], duration)
                if not keeps:
                    raise HTTPException(
                        status_code=400,
                        detail="That range would remove the entire audio",
                    )
                try:
                    await audio_editor.render_with_keeps(current_path, keeps, next_path)
                except RuntimeError as exc:
                    raise HTTPException(status_code=500, detail=str(exc))
                current_transcript = _shift_transcript_after_delete(
                    current_transcript, start, end
                )
                labels.append(f"Removed {_fmt_mmss(start)}–{_fmt_mmss(end)}")
                executed_types.append("delete_range")
                current_path = next_path
                continue

            # ---- apply_operation ------------------------------------------
            if kind != "apply_operation":
                continue
            op_type = (op.get("type") or "").upper()
            params = op.get("params") or {}

            # API op: ElevenLabs Voice Isolator handles noise + reverb
            if op_type in audio_editor.API_OPERATIONS:
                if not voice_service.is_configured():
                    raise HTTPException(
                        status_code=503,
                        detail="ELEVENLABS_API_KEY not configured for noise/reverb removal",
                    )
                with open(current_path, "rb") as f:
                    audio_bytes = f.read()
                try:
                    cleaned = await voice_service.audio_isolate(
                        audio_bytes, content_type="audio/mpeg"
                    )
                except voice_service.VoiceError as exc:
                    raise HTTPException(
                        status_code=502, detail=f"{op_type}: {exc}"
                    )
                with open(next_path, "wb") as f:
                    f.write(cleaned)
                labels.append(
                    "Removed background noise"
                    if op_type == "NOISE_REMOVAL"
                    else "Removed reverb"
                )
                executed_types.append(op_type)
                current_path = next_path
                continue

            # Transcript op: REMOVE_FILLERS
            if op_type in audio_editor.TRANSCRIPT_OPERATIONS:
                if op_type == "REMOVE_FILLERS":
                    if not current_transcript:
                        raise HTTPException(
                            status_code=400,
                            detail="Need a transcript before removing fillers — wait for transcription",
                        )
                    filler_refs = fillers_service.find_fillers(current_transcript)
                    if not filler_refs:
                        # Nothing to do — copy through.
                        shutil.copyfile(current_path, next_path)
                        labels.append("No filler words found")
                        executed_types.append(op_type)
                        current_path = next_path
                        continue

                    delete_ranges: List[Tuple[float, float]] = []
                    ref_tuples: List[Tuple[int, int]] = []
                    for ref in filler_refs:
                        # find_fillers returns (segment_idx, word_idx) tuples
                        si, wi = ref if isinstance(ref, tuple) else (
                            ref.get("segment_idx"), ref.get("word_idx")
                        )
                        r = _word_range(current_transcript, si, wi)
                        if r:
                            delete_ranges.append(r)
                            ref_tuples.append((si, wi))
                    duration = await audio_editor.probe_duration(current_path)
                    if duration <= 0:
                        raise HTTPException(status_code=500, detail="Could not probe audio duration")
                    keeps = audio_editor.keep_ranges(delete_ranges, duration)
                    if not keeps:
                        raise HTTPException(
                            status_code=400,
                            detail="Filler removal would erase the entire audio",
                        )
                    try:
                        await audio_editor.render_with_keeps(current_path, keeps, next_path)
                    except RuntimeError as exc:
                        raise HTTPException(status_code=500, detail=str(exc))
                    current_transcript = _apply_edits_to_transcript(
                        current_transcript, ref_tuples, []
                    )
                    n = len(ref_tuples)
                    labels.append(f"Removed {n} filler word{'' if n == 1 else 's'}")
                    executed_types.append(op_type)
                    current_path = next_path
                    continue

            # FFmpeg op: single filter-chain pass
            if op_type in audio_editor.FFMPEG_OPERATIONS:
                try:
                    audio_filter, label = audio_editor.build_operation_filter(
                        op_type, params
                    )
                except ValueError as exc:
                    raise HTTPException(status_code=400, detail=str(exc))
                try:
                    await audio_editor.apply_audio_filter(
                        current_path, next_path, audio_filter
                    )
                except RuntimeError as exc:
                    raise HTTPException(status_code=500, detail=str(exc))
                labels.append(label)
                executed_types.append(op_type)
                current_path = next_path
                continue

            # Anything else is a parser bug — bail loudly.
            raise HTTPException(
                status_code=500, detail=f"Pipeline can't execute op {op_type}"
            )

        # Read final output before the temp dir disappears.
        with open(current_path, "rb") as f:
            final_bytes = f.read()
        new_duration = await audio_editor.probe_duration(current_path)

    if not executed_types:
        raise HTTPException(status_code=400, detail="No ops executed")

    try:
        public_url = await storage_upload(
            user_id=_user_id(user),
            filename=f"chat_pipeline_{project.id}.mp3",
            data=final_bytes,
            content_type="audio/mpeg",
        )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Upload processed audio: {exc}")

    new_transcript = copy.deepcopy(current_transcript) if current_transcript else None
    if new_transcript is not None:
        new_transcript["duration"] = new_duration

    label = " · ".join(labels)
    if len(label) > 110:
        label = label[:107] + "..."

    version = AudioVersion(
        project_id=project.id,
        parent_id=project.active_version_id,
        label=label,
        audio_url=public_url,
        transcript=new_transcript,
        duration=new_duration,
    )
    db.add(version)
    await db.flush()

    project.audio_url = public_url
    project.transcript = new_transcript
    project.active_version_id = version.id
    if new_transcript is not None:
        flag_modified(project, "transcript")
    await db.commit()
    await db.refresh(version)
    return version, executed_types


@router.get("/{project_id}/processing", response_model=ProcessingStatus)
async def processing_status(
    project_id: int,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Derive processing state from the project's current fields so the
    Processing screen reflects reality rather than a hardcoded mock."""
    project = await _get_owned_project(db, project_id, user)

    if not project.audio_url:
        step, progress, complete = "uploading", 0.1, False
    elif not project.transcript:
        step, progress, complete = "transcribing", 0.55, False
    else:
        segments = (project.transcript or {}).get("segments") or []
        if not segments:
            step, progress, complete = "scanning", 0.85, False
        else:
            step, progress, complete = "ready", 1.0, True

    return ProcessingStatus(
        project_id=project_id,
        step=step,
        progress=progress,
        complete=complete,
    )


@router.post("/{project_id}/export", response_model=ExportResult)
async def export_project(
    project_id: int,
    payload: ExportRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await _get_owned_project(db, project_id, user)

    fmt = (payload.format or "mp3").lower()
    if fmt not in audio_editor.FORMAT_SPECS:
        raise HTTPException(status_code=400, detail=f"Unsupported format: {fmt}")
    if not audio_editor.ffmpeg_available():
        raise HTTPException(status_code=503, detail="FFmpeg not available on server")

    # Resolve source — explicit version_id wins, else the project's active audio.
    source_url: Optional[str] = project.audio_url
    chosen_version_id: Optional[int] = None
    if payload.version_id is not None:
        result = await db.execute(
            select(AudioVersion).where(
                AudioVersion.id == payload.version_id,
                AudioVersion.project_id == project_id,
            )
        )
        version = result.scalar_one_or_none()
        if not version:
            raise HTTPException(status_code=404, detail="Version not found")
        source_url = version.audio_url
        chosen_version_id = version.id
    else:
        chosen_version_id = project.active_version_id

    if not source_url:
        raise HTTPException(status_code=400, detail="Project has no audio to export")

    # Sanitize filename — strip any extension the user typed, replace bad chars.
    raw_name = (payload.filename or project.name or "audio").strip()
    base_name = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", raw_name)
    base_name = re.sub(r"[^A-Za-z0-9._-]+", "_", base_name).strip("_") or "audio"

    spec = audio_editor.FORMAT_SPECS[fmt]
    out_filename = f"{base_name}.{spec['ext']}"

    with tempfile.TemporaryDirectory() as tmp:
        src_path = os.path.join(tmp, "source.bin")
        out_path = os.path.join(tmp, out_filename)
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.get(source_url)
            r.raise_for_status()
            with open(src_path, "wb") as f:
                f.write(r.content)
        await audio_editor.transcode(src_path, out_path, fmt)
        with open(out_path, "rb") as f:
            data = f.read()
        download_url = await storage_upload(
            _user_id(user),
            out_filename,
            data,
            content_type=spec["content_type"],
        )

    project.status = "Exported"
    await db.commit()

    return ExportResult(
        download_url=download_url,
        filename=out_filename,
        size_bytes=len(data),
        format=fmt,
        version_id=chosen_version_id,
    )


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


@router.post("/{project_id}/operations/apply", response_model=AudioVersionOut)
async def apply_operation(
    project_id: int,
    payload: ApplyOperationRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Apply a one-shot FFmpeg audio operation (hum/loudness/silence/volume/etc).
    Each call creates a new AudioVersion."""
    project = await _get_owned_project(db, project_id, user)
    if not project.audio_url:
        raise HTTPException(status_code=400, detail="Project has no audio")
    if not audio_editor.ffmpeg_available():
        raise HTTPException(status_code=503, detail="ffmpeg not installed on the server")
    if not storage_configured():
        raise HTTPException(status_code=503, detail="Storage not configured")

    op_type = (payload.type or "").upper()
    # This endpoint only runs single-pass FFmpeg ops. API ops, transcript
    # ops, and meta pipelines go through /chat which has the multi-op
    # executor.
    if op_type not in audio_editor.FFMPEG_OPERATIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported operation '{payload.type}'. Supported: {sorted(audio_editor.FFMPEG_OPERATIONS)}",
        )
    try:
        audio_filter, default_label = audio_editor.build_operation_filter(
            op_type, payload.params or {}
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Pick source (parent version's URL if provided, else current).
    source_url = project.audio_url
    source_transcript = project.transcript
    parent_id = payload.parent_version_id
    if parent_id is not None:
        result = await db.execute(
            select(AudioVersion).where(
                AudioVersion.id == parent_id,
                AudioVersion.project_id == project_id,
            )
        )
        parent = result.scalar_one_or_none()
        if parent:
            source_url = parent.audio_url
            source_transcript = parent.transcript or source_transcript

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

        try:
            await audio_editor.apply_audio_filter(src_path, out_path, audio_filter)
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc))

        with open(out_path, "rb") as f:
            rendered = f.read()
        new_duration = await audio_editor.probe_duration(out_path)

    try:
        public_url = await storage_upload(
            user_id=_user_id(user),
            filename=f"op_{op_type.lower()}_{project_id}.mp3",
            data=rendered,
            content_type="audio/mpeg",
        )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Upload processed audio: {exc}")

    # Transcript is unchanged by these filter operations — they don't cut time
    # except TRIM_SILENCE (which removes head/tail silence). For TRIM_SILENCE
    # the transcript word timings would technically shift, but the surgical
    # fix-up is non-trivial; we keep the source transcript and update duration.
    new_transcript = copy.deepcopy(source_transcript) if source_transcript else None
    if new_transcript is not None:
        new_transcript["duration"] = new_duration

    version = AudioVersion(
        project_id=project_id,
        parent_id=parent_id,
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
    if new_transcript is not None:
        flag_modified(project, "transcript")
    await db.commit()
    await db.refresh(version)
    return AudioVersionOut.model_validate(version)


def _shift_transcript_after_delete(
    transcript: Optional[dict], start: float, end: float
) -> Optional[dict]:
    """After deleting [start,end) from the audio, drop words that fell in
    the cut and shift everything after it earlier by (end - start).
    Returns a new dict; caller is responsible for re-flagging the JSON column."""
    if not transcript:
        return transcript
    cut = max(0.0, end - start)
    new_segments: List[dict] = []
    for seg in transcript.get("segments") or []:
        seg_start = float(seg.get("start", 0.0))
        seg_end = float(seg.get("end", 0.0))
        # Segment lies entirely inside the deleted window — drop it.
        if seg_end <= start or seg_start >= end:
            # Outside the cut. If it's after, shift it.
            if seg_start >= end:
                seg = {
                    **seg,
                    "start": seg_start - cut,
                    "end": seg_end - cut,
                    "words": [
                        {**w, "start": float(w.get("start", 0.0)) - cut,
                         "end": float(w.get("end", 0.0)) - cut}
                        for w in (seg.get("words") or [])
                        if float(w.get("start", 0.0)) >= end
                    ],
                }
            new_segments.append(seg)
            continue
        # Segment straddles or sits inside the cut — keep words outside the window.
        kept_words = []
        for w in seg.get("words") or []:
            ws = float(w.get("start", 0.0))
            we = float(w.get("end", ws))
            if we <= start:
                kept_words.append({**w})
            elif ws >= end:
                kept_words.append({**w, "start": ws - cut, "end": we - cut})
            # else: word overlaps the cut — drop it
        if not kept_words:
            continue
        new_segments.append({
            **seg,
            "start": kept_words[0]["start"],
            "end": kept_words[-1]["end"],
            "words": kept_words,
            "text": " ".join(w.get("text", "").strip() for w in kept_words).strip(),
        })
    full_text = " ".join(s.get("text", "").strip() for s in new_segments).strip()
    return {
        **transcript,
        "duration": max(0.0, float(transcript.get("duration", 0.0)) - cut),
        "text": full_text,
        "segments": new_segments,
    }


@router.post("/{project_id}/operations/delete-range", response_model=AudioVersionOut)
async def delete_range(
    project_id: int,
    payload: DeleteRangeRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a single time range from the project audio.

    Uses the existing render_with_keeps path (with a tiny crossfade at the
    splice point), updates the transcript by removing words inside the cut
    and shifting timestamps after it. Creates a new AudioVersion.
    """
    project = await _get_owned_project(db, project_id, user)
    if not project.audio_url:
        raise HTTPException(status_code=400, detail="Project has no audio")
    if not audio_editor.ffmpeg_available():
        raise HTTPException(status_code=503, detail="ffmpeg not installed on the server")
    if not storage_configured():
        raise HTTPException(status_code=503, detail="Storage not configured")

    start = max(0.0, float(payload.start_seconds))
    end = float(payload.end_seconds)
    if end <= start:
        raise HTTPException(status_code=400, detail="end_seconds must be greater than start_seconds")

    # Pick source.
    source_url = project.audio_url
    source_transcript = project.transcript
    parent_id = payload.parent_version_id
    if parent_id is not None:
        result = await db.execute(
            select(AudioVersion).where(
                AudioVersion.id == parent_id,
                AudioVersion.project_id == project_id,
            )
        )
        parent = result.scalar_one_or_none()
        if parent:
            source_url = parent.audio_url
            source_transcript = parent.transcript or source_transcript

    with tempfile.TemporaryDirectory() as tmp:
        src_path = os.path.join(tmp, "in.mp3")
        out_path = os.path.join(tmp, "out.mp3")

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.get(source_url)
                resp.raise_for_status()
                with open(src_path, "wb") as f:
                    f.write(resp.content)
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Fetch source audio: {exc}")

        duration = await audio_editor.probe_duration(src_path)
        if duration <= 0:
            raise HTTPException(status_code=500, detail="Could not probe audio duration")
        # Clamp end to the source duration so the user can say "remove from 30s to forever".
        end = min(end, duration)
        if end <= start:
            raise HTTPException(status_code=400, detail="Range is outside the audio")

        keeps = audio_editor.keep_ranges([(start, end)], duration)
        if not keeps:
            raise HTTPException(
                status_code=400,
                detail="Deleting that range would remove the entire audio",
            )

        try:
            await audio_editor.render_with_keeps(src_path, keeps, out_path)
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc))

        with open(out_path, "rb") as f:
            rendered = f.read()
        new_duration = await audio_editor.probe_duration(out_path)

    try:
        public_url = await storage_upload(
            user_id=_user_id(user),
            filename=f"cut_{project_id}.mp3",
            data=rendered,
            content_type="audio/mpeg",
        )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Upload processed audio: {exc}")

    new_transcript = _shift_transcript_after_delete(source_transcript, start, end)
    if new_transcript is not None:
        new_transcript["duration"] = new_duration

    def _fmt(t: float) -> str:
        m, s = divmod(int(t), 60)
        return f"{m}:{s:02d}"

    version = AudioVersion(
        project_id=project_id,
        parent_id=parent_id,
        label=payload.label or f"Removed {_fmt(start)}–{_fmt(end)}",
        audio_url=public_url,
        transcript=new_transcript,
        duration=new_duration,
    )
    db.add(version)
    await db.flush()

    project.audio_url = public_url
    project.transcript = new_transcript
    project.active_version_id = version.id
    if new_transcript is not None:
        flag_modified(project, "transcript")
    await db.commit()
    await db.refresh(version)
    return AudioVersionOut.model_validate(version)
