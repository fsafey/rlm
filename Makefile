.PHONY: help install install-dev install-modal run-all \
        quickstart docker-repl lm-repl modal-repl \
        lint format test check backend frontend tunnel \
        admin admin-dev

help:
	@echo "RLM Examples Makefile"
	@echo ""
	@echo "Usage:"
	@echo "  make install        - Install base dependencies with uv"
	@echo "  make install-dev    - Install dev dependencies with uv"
	@echo "  make install-modal  - Install modal dependencies with uv"
	@echo "  make run-all        - Run all examples (requires all deps and API keys)"
	@echo ""
	@echo "Examples:"
	@echo "  make quickstart     - Run quickstart.py (needs OPENAI_API_KEY)"
	@echo "  make docker-repl    - Run docker_repl_example.py (needs Docker)"
	@echo "  make lm-repl        - Run lm_in_repl.py (needs PORTKEY_API_KEY)"
	@echo "  make modal-repl     - Run modal_repl_example.py (needs Modal)"
	@echo ""
	@echo "Development:"
	@echo "  make lint           - Run ruff linter"
	@echo "  make format         - Run ruff formatter"
	@echo "  make test           - Run tests"
	@echo "  make check          - Run lint + format + tests"
	@echo "  make backend        - Start rlm_search API server (SEARCH_BACKEND_PORT, default 8092)"
	@echo "  make admin          - Launch admin workbench and open RLM search page"
	@echo "  make admin-dev      - Same as admin, but uses THIS repo's RLM backend on :8092"

install:
	uv sync

install-dev:
	uv sync --group dev --group test --group search

install-modal:
	uv pip install -e ".[modal]"

run-all: quickstart docker-repl lm-repl modal-repl

quickstart: install
	uv run python -m examples.quickstart

docker-repl: install
	uv run python -m examples.docker_repl_example

lm-repl: install
	uv run python -m examples.lm_in_repl

modal-repl: install-modal
	uv run python -m examples.modal_repl_example

lint: install-dev
	uv run ruff check .

format: install-dev
	uv run ruff format .

test: install-dev
	uv run pytest

check: lint format test

backend:
	PORT=$${SEARCH_BACKEND_PORT:-8092}; \
	trap 'lsof -ti :'"$$PORT"' | xargs kill -9 2>/dev/null; exit 0' INT TERM; \
	uv run uvicorn rlm_search.api:app --port $$PORT --app-dir $(CURDIR) 2>&1 | tee /tmp/rlm_search

ADMIN_DIR ?= /Users/farieds/Project/standalone-search/4_FRONTEND_ADMIN
ADMIN_URL  = http://localhost:4173/rlm-search

admin:
	@ADMIN_DIR=$(ADMIN_DIR) ./scripts/admin-dev.sh --no-backend

admin-dev:
	@ADMIN_DIR=$(ADMIN_DIR) ./scripts/admin-dev.sh
