.PHONY: help install install-dev install-modal run-all \
        quickstart docker-repl lm-repl modal-repl \
        lint format test check backend frontend tunnel

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
	@echo "  make frontend       - Start search frontend (SEARCH_FRONTEND_PORT, default 3002)"
	@echo "  make tunnel         - Start backend + frontend + Cloudflare Tunnel (shareable URL)"

install:
	uv sync

install-dev:
	uv sync --group dev --group test

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

frontend:
	cd search-app && SEARCH_FRONTEND_PORT=$${SEARCH_FRONTEND_PORT:-3002} SEARCH_BACKEND_PORT=$${SEARCH_BACKEND_PORT:-8092} npm run dev

tunnel:
	@echo "Starting RLM Search with Cloudflare Tunnel..."
	@BPORT=$${SEARCH_BACKEND_PORT:-8092}; FPORT=$${SEARCH_FRONTEND_PORT:-3002}; \
	echo "Backend: http://localhost:$$BPORT"; \
	echo "Frontend: http://localhost:$$FPORT"; \
	echo ""; \
	echo "Killing existing processes on ports $$BPORT and $$FPORT..."; \
	lsof -ti :$$BPORT :$$FPORT 2>/dev/null | xargs kill 2>/dev/null || true; \
	sleep 1; \
	$(MAKE) backend & \
	sleep 2; \
	$(MAKE) frontend & \
	sleep 3; \
	cloudflared tunnel --url http://localhost:$$FPORT
