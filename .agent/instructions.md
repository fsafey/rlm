# Antigravity Project Instructions

This project uses `uv` for dependency management and `Makefile` for running common tasks.

## Key Commands

- **Install Dependencies**: `make install` (uses `uv sync`)
- **Run Tests**: `make test` (uses `uv run pytest`)
- **Lint/Format**: `make check` (runs lint, format, and test)
- **Start Backend**: `make backend`
- **Start Frontend**: `make frontend`

## Project Structure

- `rlm/`: Core Recursive Language Model logic
- `rlm_search/`: Search backend implementation
- `search-app/`: Frontend application
- `visualizer/`: RLM trajectory visualizer
- `examples/`: Example scripts
