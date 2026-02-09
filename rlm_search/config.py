"""Environment configuration for RLM agentic search."""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

CASCADE_API_URL = os.getenv("CASCADE_API_URL", "http://localhost:8091")
CASCADE_API_KEY = os.getenv("CASCADE_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
RLM_BACKEND = os.getenv("RLM_BACKEND", "anthropic")
RLM_MODEL = os.getenv("RLM_MODEL", "claude-sonnet-4-20250514")
RLM_MAX_ITERATIONS = int(os.getenv("RLM_MAX_ITERATIONS", "15"))
RLM_MAX_DEPTH = int(os.getenv("RLM_MAX_DEPTH", "1"))
