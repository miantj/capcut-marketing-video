#!/bin/sh
set -eu
cd "$(dirname "$0")"
PORT="${PORT:-8766}"
LISTEN_ADDRESS="${LISTEN_ADDRESS:-0.0.0.0}"
PYTHON="${PYTHON:-}"
if [ -z "$PYTHON" ]; then
  bootstrap_py=""
  for c in python3.13 python3.12 python3.11 python3; do
    command -v "$c" >/dev/null 2>&1 || continue
    "$c" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" || continue
    bootstrap_py="$c"
    break
  done
  if [ -z "$bootstrap_py" ]; then
    echo "Need Python 3.11+ to create .venv (system python3 is too old)." >&2
    exit 1
  fi
  if [ ! -x .venv/bin/python ] || ! .venv/bin/python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"; then
    "$bootstrap_py" -m venv .venv
  fi
  PYTHON=.venv/bin/python
  "$PYTHON" -c "import uvicorn" 2>/dev/null || "$PYTHON" -m pip install -r requirements.txt
fi
if [ ! -f node_modules/capcut-cli/dist/index.js ]; then
  command -v npm >/dev/null 2>&1 || { echo "Need npm to install capcut-cli." >&2; exit 1; }
  npm install capcut-cli
fi
export PATH="$(pwd)/node_modules/.bin:${PATH}"
if [ -z "${VIDEO_SKILL_DIR:-}" ] && [ -d "../capcut-marketing-video/scripts" ]; then
  export VIDEO_SKILL_DIR="$(cd ../capcut-marketing-video && pwd)"
elif [ -z "${VIDEO_SKILL_DIR:-}" ] && [ -d "../scripts" ]; then
  export VIDEO_SKILL_DIR="$(cd .. && pwd)"
fi
echo "Video workspace: http://localhost:${PORT}"
exec "$PYTHON" -m uvicorn workbench.app:app --host "$LISTEN_ADDRESS" --port "$PORT" --workers 1 --timeout-graceful-shutdown 3
