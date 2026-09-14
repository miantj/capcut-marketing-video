#!/bin/sh
set -eu
cd "$(dirname "$0")"
PORT="${PORT:-8766}"
LISTEN_ADDRESS="${LISTEN_ADDRESS:-0.0.0.0}"
PYTHON="${PYTHON:-}"
if [ -z "$PYTHON" ]; then
  [ -x .venv/bin/python ] && PYTHON=.venv/bin/python || PYTHON="$(command -v python3 || command -v python)"
fi
if [ -z "${VIDEO_SKILL_DIR:-}" ] && [ -d "../scripts" ]; then export VIDEO_SKILL_DIR="$(cd .. && pwd)"; fi
echo "Video workspace: http://localhost:${PORT}"
exec "$PYTHON" -m uvicorn workbench.app:app --host "$LISTEN_ADDRESS" --port "$PORT" --workers 1 --timeout-graceful-shutdown 3
