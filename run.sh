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

CT_DIR="$SCRIPT_DIR/customsandtaxriskmanagemensystem"
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

CT_DIST="$CT_DIR/dist"
if [[ -f "$CT_DIST/index.html" ]]; then
  CT_MODE="static (python http.server, dist/)"
else
  CT_MODE="dev (npm run dev, requires node_modules)"
fi

echo "── Starting services ───────────────────────────────────────────"
echo "  Backend:         http://localhost:${BACKEND_PORT}"
echo "  C&T dashboard:   http://localhost:${CT_FRONTEND_PORT}  [${CT_MODE}]"
echo "  Press Ctrl-C to stop both."
echo "────────────────────────────────────────────────────────────────"

# Backend — API_PORT env var drives lib/config.py; uvicorn --port mirrors it.
API_PORT="$BACKEND_PORT" python -m uvicorn api:app --host 0.0.0.0 --port "$BACKEND_PORT" &
BACKEND_PID=$!

# C&T dashboard — packaged installs ship pre-built dist/ and serve it
# via Python's http.server (no node at runtime). Dev installs (no
# dist/) fall back to Vite's dev server.
if [[ -f "$CT_DIST/index.html" ]]; then
  (cd "$CT_DIST" && python -m http.server "$CT_FRONTEND_PORT" \
                                  --bind 0.0.0.0) &
else
  (cd "$CT_DIR" && PORT="$CT_FRONTEND_PORT" npm run dev) &
fi
CT_PID=$!

cleanup() {
  echo ""
  echo "Stopping services…"
  kill "$BACKEND_PID" "$CT_PID" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

wait
