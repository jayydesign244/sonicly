from pydantic import BaseModel, EmailStr
from typing import Any, Optional, List
from datetime import datetime
from enum import Enum


class ProjectStatus(str, Enum):
    new = "New"
    in_progress = "In Progress"
    exported = "Exported"


class UserCreate(BaseModel):
    name: str
    email: EmailStr
    password: str


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: int
    name: str
    email: str

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class ProjectCreate(BaseModel):
    name: str
    duration: Optional[str] = None


class ProjectOut(BaseModel):
    id: int
    name: str
    duration: Optional[str] = None
    status: ProjectStatus = ProjectStatus.new
    audio_url: Optional[str] = None
    transcript: Optional[dict] = None
    active_version_id: Optional[int] = None
    voice_id: Optional[str] = None
    voice_provider: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AudioVersionOut(BaseModel):
    id: int
    project_id: int
    parent_id: Optional[int] = None
    label: str
    audio_url: str
    transcript: Optional[dict] = None
    duration: Optional[float] = None
    created_at: datetime

    class Config:
        from_attributes = True


class WordRef(BaseModel):
    segment_idx: int
    word_idx: int


class DeleteEdit(BaseModel):
    type: str = "delete"
    words: List[WordRef]


class ReplaceEdit(BaseModel):
    type: str = "replace"
    word: WordRef
    new_text: str


class ApplyEditsRequest(BaseModel):
    parent_version_id: Optional[int] = None
    label: Optional[str] = None
    edits: List[dict]


class ApplyOperationRequest(BaseModel):
    """One-shot audio operation (FFmpeg primitive). See audio_editor.SUPPORTED_OPERATIONS."""
    type: str
    params: Optional[dict] = None
    parent_version_id: Optional[int] = None
    label: Optional[str] = None


class DeleteRangeRequest(BaseModel):
    """Cut a single time range out of the audio. Timestamps in seconds."""
    start_seconds: float
    end_seconds: float
    parent_version_id: Optional[int] = None
    label: Optional[str] = None


class FillersResponse(BaseModel):
    fillers: List[WordRef]
    total: int


class TranscriptWord(BaseModel):
    text: str
    start: float
    end: float


class TranscriptSegment(BaseModel):
    start: float
    end: float
    text: str
    words: List[TranscriptWord]


class Transcript(BaseModel):
    language: Optional[str] = None
    duration: Optional[float] = None
    text: str
    segments: List[TranscriptSegment]


class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    messages: List[ChatMessage]


class ChatResponse(BaseModel):
    message: str
    version_created: bool = False


class ProcessingStatus(BaseModel):
    project_id: int
    step: str
    progress: float
    complete: bool


class ExportRequest(BaseModel):
    format: str = "mp3"  # mp3 | wav | m4a
    version_id: Optional[int] = None  # default: project's active version
    filename: Optional[str] = None  # without extension; we append the right one


class ExportResult(BaseModel):
    download_url: str
    filename: str
    size_bytes: int
    format: str
    version_id: Optional[int] = None
