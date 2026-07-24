#!/usr/bin/env bash
# web/run.sh — Start the coding-vibe Web UI server.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

# Prefer venv if it exists; fall back to system python
if [ -d "$SCRIPT_DIR/.venv" ]; then
  source "$SCRIPT_DIR/.venv/bin/activate"
fi

# Load .env from project root
if [ -f "$SCRIPT_DIR/.env" ]; then
  export $(grep -v '^#' "$SCRIPT_DIR/.env" | grep -v '^$' | xargs) 2>/dev/null || true
fi

export PYTHONPATH="$SCRIPT_DIR${PYTHONPATH:+:$PYTHONPATH}"

echo "🚀 Starting Coding Vibe Web UI on http://127.0.0.1:5091"
echo "   Static dir: $SCRIPT_DIR/web/static"

uvicorn web.server:app \
  --host 127.0.0.1 \
  --port 5091 \
  --reload
