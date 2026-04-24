#!/usr/bin/env bash
# Launch both the backend and the C&T operator dashboard.
# Reads ports from config.env. Press Ctrl-C to stop both.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

BACKEND_PORT=8505
CT_FRONTEND_PORT=8080
if [[ -f "$SCRIPT_DIR/config.env" ]]; then
  # shellcheck disable=SC1091
  source "$SCRIPT_DIR/config.env"
fi

CT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)/customsandtaxriskmanagemensystem"
if [[ ! -d "$CT_DIR" ]]; then
  echo "!! C&T frontend not found at $CT_DIR. Run ./install.sh first." >&2
  exit 1
fi

VENV_DIR="$SCRIPT_DIR/.venv"
if [[ -f "$VENV_DIR/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "$VENV_DIR/bin/activate"
else
  echo "!! Python venv not found at $VENV_DIR. Run ./install.sh first." >&2
  exit 1
fi

echo "── Starting services ───────────────────────────────────────────"
echo "  Backend:         http://localhost:${BACKEND_PORT}"
echo "  C&T dashboard:   http://localhost:${CT_FRONTEND_PORT}"
echo "  Press Ctrl-C to stop both."
echo "────────────────────────────────────────────────────────────────"

# Backend — API_PORT env var drives lib/config.py; uvicorn --port mirrors it.
API_PORT="$BACKEND_PORT" python -m uvicorn api:app --host 0.0.0.0 --port "$BACKEND_PORT" &
BACKEND_PID=$!

# C&T dashboard — PORT env var drives vite.config.ts
(cd "$CT_DIR" && PORT="$CT_FRONTEND_PORT" npm run dev) &
CT_PID=$!

cleanup() {
  echo ""
  echo "Stopping services…"
  kill "$BACKEND_PID" "$CT_PID" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

wait
