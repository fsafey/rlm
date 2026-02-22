"""Environment configuration for RLM agentic search."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Prevent CLAUDECODE env var from leaking to nested CLI invocations
os.environ.pop("CLAUDECODE", None)

# Load .env from project root (parent of rlm_search/)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")

CASCADE_API_URL = os.getenv("CASCADE_API_URL", "https://cascade.imam-us.org")
CASCADE_API_KEY = os.getenv("CASCADE_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
RLM_BACKEND = os.getenv("RLM_BACKEND", "anthropic")
RLM_MODEL = os.getenv("RLM_MODEL", "claude-opus-4-6")
RLM_SUB_MODEL = os.getenv("RLM_SUB_MODEL", "claude-sonnet-4-6")
RLM_MAX_ITERATIONS = int(os.getenv("RLM_MAX_ITERATIONS", "15"))
RLM_MAX_DEPTH = int(os.getenv("RLM_MAX_DEPTH", "1"))
RLM_SUB_ITERATIONS = int(os.getenv("RLM_SUB_ITERATIONS", "3"))
# WARNING: values > 1 allow multiplicative iteration growth (e.g. 15 × 3 × 2 = 90 LLM calls).
RLM_MAX_DELEGATION_DEPTH = max(0, int(os.getenv("RLM_MAX_DELEGATION_DEPTH", "1")))
RLM_CLASSIFY_MODEL = os.getenv("RLM_CLASSIFY_MODEL", "claude-sonnet-4-6")
SESSION_TIMEOUT = int(os.getenv("SESSION_TIMEOUT", "1800"))  # 30 min default
SEARCH_BACKEND_PORT = int(os.getenv("SEARCH_BACKEND_PORT", "8092"))
SEARCH_FRONTEND_PORT = int(os.getenv("SEARCH_FRONTEND_PORT", "3002"))

print(
    f"[CONFIG] cascade={CASCADE_API_URL} backend={RLM_BACKEND} model={RLM_MODEL} sub_model={RLM_SUB_MODEL or '(same)'} classify_model={RLM_CLASSIFY_MODEL} max_iter={RLM_MAX_ITERATIONS} sub_iter={RLM_SUB_ITERATIONS} max_depth={RLM_MAX_DEPTH} max_deleg_depth={RLM_MAX_DELEGATION_DEPTH} backend_port={SEARCH_BACKEND_PORT} frontend_port={SEARCH_FRONTEND_PORT}"
)
print(
    f"[CONFIG] api_keys: anthropic={'SET' if ANTHROPIC_API_KEY else 'MISSING'} cascade={'SET' if CASCADE_API_KEY else 'MISSING'}"
)
