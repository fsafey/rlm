#!/bin/bash
# Start RLM backend from this repo + admin workbench, clean exit on Ctrl+C.
# Usage: ./scripts/admin-dev.sh [--no-backend]
#   --no-backend  Skip starting local RLM; just open admin workbench.

set -e

RLM_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ADMIN_DIR="${ADMIN_DIR:-/Users/farieds/Project/standalone-search/4_FRONTEND_ADMIN}"
PORT="${SEARCH_BACKEND_PORT:-8092}"
ADMIN_URL="http://localhost:4173/rlm-search"

BACKEND_PID=""
ADMIN_PID=""

cleanup() {
    echo ""
    echo "Shutting down..."
    [ -n "$ADMIN_PID" ]   && kill "$ADMIN_PID"   2>/dev/null
    [ -n "$BACKEND_PID" ] && kill "$BACKEND_PID"  2>/dev/null
    wait 2>/dev/null
    echo "Done."
}
trap cleanup EXIT

NO_BACKEND=0
[ "${1:-}" = "--no-backend" ] && NO_BACKEND=1

if [ "$NO_BACKEND" -eq 0 ]; then
    echo "Starting RLM backend from this repo on :$PORT ..."
    cd "$RLM_DIR" && make backend &
    BACKEND_PID=$!
    until curl -s -o /dev/null "http://localhost:$PORT/health" 2>/dev/null; do sleep 1; done
    echo "RLM backend ready on :$PORT"
fi

echo "Starting admin workbench ..."
cd "$ADMIN_DIR" && make start &
ADMIN_PID=$!
until curl -s -o /dev/null http://localhost:4173 2>/dev/null; do sleep 1; done
open "$ADMIN_URL"

echo "Running → $ADMIN_URL  (Ctrl+C to stop)"
wait
