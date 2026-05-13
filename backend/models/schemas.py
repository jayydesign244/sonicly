from pydantic import BaseModel, EmailStr
from typing import Optional, List
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
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


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
    project_id: int
    format: str
    version: str
    filename: str
