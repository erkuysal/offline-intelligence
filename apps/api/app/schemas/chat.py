from typing import Literal
from datetime import datetime
from uuid import uuid4
import time

from pydantic import BaseModel, ConfigDict, Field


ChatRole = Literal["system", "user", "assistant"]


class ChatMessage(BaseModel):
    role: ChatRole
    content: str = Field(min_length=1, max_length=20000)


class ChatCompletionRequest(BaseModel):
    model: str | None = Field(default=None, min_length=1, max_length=100)
    messages: list[ChatMessage] = Field(min_length=1, max_length=100)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=512, ge=1, le=4096)
    stream: bool = False
    use_documents: bool = False
    document_ids: list[int] | None = Field(default=None, min_length=1, max_length=100)
    retrieval_limit: int | None = Field(default=None, ge=1, le=20)
    conversation_id: int | None = Field(default=None, ge=1)


class ChatCompletionChoice(BaseModel):
    index: int
    message: ChatMessage
    finish_reason: str


class ChatUsage(BaseModel):
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)


class ChatSource(BaseModel):
    document_id: int
    document_filename: str
    chunk_id: int
    chunk_index: int
    source_page: int | None
    source_label: str | None
    score: float


class ChatCompletionResponse(BaseModel):
    id: str = Field(default_factory=lambda: f"chatcmpl-{uuid4().hex}")
    object: Literal["chat.completion"] = "chat.completion"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str
    choices: list[ChatCompletionChoice]
    usage: ChatUsage | None = None
    sources: list[ChatSource] | None = None
    conversation_id: int | None = None


class ConversationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_id: int
    title: str | None
    created_at: datetime
    updated_at: datetime


class ConversationSourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: int
    document_filename: str
    chunk_id: int | None
    chunk_index: int
    source_page: int | None
    source_label: str | None
    score: float


class ConversationMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    conversation_id: int
    role: str
    content: str
    model: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    sources: list[ConversationSourceRead]
    created_at: datetime
