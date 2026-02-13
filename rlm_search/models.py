"""Pydantic models for the RLM search API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query: str
    settings: SearchSettings | None = None
    session_id: str | None = None  # None = new session; set for follow-up


class SearchSettings(BaseModel):
    backend: str | None = None
    model: str | None = None
    sub_model: str | None = None
    max_iterations: int | None = None
    max_depth: int | None = None


class SearchResponse(BaseModel):
    search_id: str
    session_id: str


class SearchSource(BaseModel):
    id: str
    question: str = ""
    answer: str = ""
    score: float = 0.0
    metadata: dict = Field(default_factory=dict)


class SearchEvent(BaseModel):
    type: str  # metadata | iteration | done | error
    data: dict = Field(default_factory=dict)


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "0.1.0"
    cascade_api: str = "connected"
    cascade_url: str | None = None
