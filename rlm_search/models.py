"""Pydantic models for the RLM search API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query: str
    collection: str = "enriched_gemini"
    settings: SearchSettings | None = None


class SearchSettings(BaseModel):
    backend: str = "anthropic"
    model: str = "claude-sonnet-4-20250514"
    max_iterations: int = 15
    max_depth: int = 1


class SearchResponse(BaseModel):
    search_id: str


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
