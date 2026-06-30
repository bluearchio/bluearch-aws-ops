"""Pydantic schemas for AI chat endpoints."""

from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """Chat message request."""

    question: str = Field(min_length=1, max_length=4000)
    model: str = Field("auto", description="Model alias: auto, haiku, sonnet, opus")
    session_id: Optional[str] = Field(
        None, description="Session ID for conversation continuity"
    )


class ChatResponse(BaseModel):
    """Non-streaming chat response."""

    answer: str
    session_id: str
    model: str
    tokens: Optional[Dict[str, int]] = None


class QuestionRequest(BaseModel):
    """Single question request (non-streaming)."""

    question: str = Field(min_length=1, max_length=4000)
    model: str = Field("haiku", description="Model alias: haiku, sonnet, opus")


class ModelInfo(BaseModel):
    """Available AI model."""

    alias: str
    model_id: str
    description: str


class ModelsResponse(BaseModel):
    """Available models list."""

    models: List[ModelInfo]
    default: str = "auto"


class ConversationSummary(BaseModel):
    """Summary of a chat conversation."""

    id: str
    title: str
    model: str = "auto"
    message_count: int = 0
    updated_at: str = ""
