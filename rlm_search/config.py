"""Environment configuration for RLM agentic search."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root (parent of rlm_search/)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")

CASCADE_API_URL = os.getenv("CASCADE_API_URL", "http://localhost:8090")
CASCADE_API_HOST = os.getenv("CASCADE_API_HOST", "localhost")
CASCADE_PORT_RANGE = os.getenv("CASCADE_PORT_RANGE", "8089-8095")
_CASCADE_URL_EXPLICIT = os.getenv("CASCADE_API_URL") is not None
CASCADE_API_KEY = os.getenv("CASCADE_API_KEY", "dev-key-change-me")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
RLM_BACKEND = os.getenv("RLM_BACKEND", "anthropic")
RLM_MODEL = os.getenv("RLM_MODEL", "claude-sonnet-4-5-20250929")
RLM_MAX_ITERATIONS = int(os.getenv("RLM_MAX_ITERATIONS", "15"))
RLM_MAX_DEPTH = int(os.getenv("RLM_MAX_DEPTH", "1"))
SEARCH_BACKEND_PORT = int(os.getenv("SEARCH_BACKEND_PORT", "8092"))
SEARCH_FRONTEND_PORT = int(os.getenv("SEARCH_FRONTEND_PORT", "3002"))

print(
    f"[CONFIG] cascade={CASCADE_API_URL} backend={RLM_BACKEND} model={RLM_MODEL} max_iter={RLM_MAX_ITERATIONS} max_depth={RLM_MAX_DEPTH} backend_port={SEARCH_BACKEND_PORT} frontend_port={SEARCH_FRONTEND_PORT}"
)
print(
    f"[CONFIG] api_keys: anthropic={'SET' if ANTHROPIC_API_KEY else 'MISSING'} cascade={'SET' if CASCADE_API_KEY else 'MISSING'}"
)
