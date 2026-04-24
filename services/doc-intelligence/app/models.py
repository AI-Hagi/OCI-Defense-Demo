"""
Pydantic request/response schemas for the Document Intelligence service.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    q: str = Field(..., min_length=1, max_length=4000)
    k: int = Field(default=10, ge=1, le=50)


class SearchHit(BaseModel):
    doc_id: str
    title: str
    chunk_idx: int
    text: str
    dist: float


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(..., min_length=1, max_length=8000)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(..., min_length=1)


class Citation(BaseModel):
    doc_id: str
    chunk_idx: int


class ChatResponse(BaseModel):
    answer: str
    citations: list[Citation]
