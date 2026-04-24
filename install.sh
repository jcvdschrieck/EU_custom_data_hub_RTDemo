#!/usr/bin/env bash
# EU Custom Data Hub — one-shot installer for macOS / Linux.
#
# What it does (idempotent):
#   1. Installs Python 3.11+ and Node.js 18+ via brew / apt if missing.
#   2. Clones the C&T frontend repo as a sibling directory if absent.
#   3. Installs Python deps (pip) and Node deps (npm) for both frontends.
#   4. Builds the internal Vite frontend into frontend/dist/.
#   5. Writes customsandtaxriskmanagemensystem/.env and
#      vat_fraud_detection/.env from config.env.
#   6. Seeds the four SQLite databases.
#
# Note: vat_fraud_detection/ is vendored — its files ship inside this
# repo as plain tree content, not as a git submodule. No submodule
# init step is needed.
#
# Optional after install:
#   cd vat_fraud_detection && python3 build_knowledge_base.py --minilm-only
#   (5 min — builds the RAG index the VAT Fraud Detection Agent cites.)
#
# Run with:  ./install.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Config ──────────────────────────────────────────────────────────────
BACKEND_PORT=8505
CT_FRONTEND_PORT=8080
LM_STUDIO_URL=http://localhost:1234
LM_STUDIO_MODEL=mistralai/mistral-7b-instruct-v0.3
# Override from config.env if present.
if [[ -f "$SCRIPT_DIR/config.env" ]]; then
  # shellcheck disable=SC1091
  source "$SCRIPT_DIR/config.env"
fi

echo "── Config ───────────────────────────────────────────────────────"
echo "  BACKEND_PORT     = $BACKEND_PORT"
echo "  CT_FRONTEND_PORT = $CT_FRONTEND_PORT"
echo "  LM_STUDIO_URL    = $LM_STUDIO_URL"
echo "  LM_STUDIO_MODEL  = $LM_STUDIO_MODEL"
echo "────────────────────────────────────────────────────────────────"

have() { command -v "$1" >/dev/null 2>&1; }

# ── Step 1: Python 3.11+ ─────────────────────────────────────────────────
install_python() {
  if have brew; then
    echo "==> Installing Python 3.11 via Homebrew"
    brew install python@3.11
  elif have apt-get; then
    echo "==> Installing Python 3.11 via apt"
    sudo apt-get update
    sudo apt-get install -y python3.11 python3-pip python3-venv
  elif have dnf; then
    sudo dnf install -y python3.11 python3-pip
  else
    echo "!! Could not detect brew / apt-get / dnf. Install Python 3.11+ manually, then re-run this script." >&2
    exit 1
  fi
}

if ! have python3; then install_python; fi
py_version=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
py_major=$(echo "$py_version" | cut -d. -f1)
py_minor=$(echo "$py_version" | cut -d. -f2)
if (( py_major < 3 )) || { (( py_major == 3 )) && (( py_minor < 11 )); }; then
  echo "!! Python $py_version is too old (need 3.11+). Install a newer version and re-run." >&2
  exit 1
fi
echo "✓ Python $py_version"

# ── Step 2: Node.js 18+ ─────────────────────────────────────────────────
install_node() {
  if have brew; then
    echo "==> Installing Node.js via Homebrew"
    brew install node
  elif have apt-get; then
    echo "==> Installing Node.js 20 LTS via nodesource"
    curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -
    sudo apt-get install -y nodejs
  elif have dnf; then
    curl -fsSL https://rpm.nodesource.com/setup_lts.x | sudo -E bash -
    sudo dnf install -y nodejs
  else
    echo "!! Could not detect a package manager. Install Node.js 18+ manually, then re-run this script." >&2
    exit 1
  fi
}
if ! have node; then install_node; fi
node_major=$(node -p 'process.versions.node.split(".")[0]')
if (( node_major < 18 )); then
  echo "!! Node.js $(node -v) is too old (need 18+). Install a newer version and re-run." >&2
  exit 1
fi
echo "✓ Node.js $(node -v)"

# ── Step 4: Python venv + deps ──────────────────────────────────────────
# A dedicated venv sidesteps PEP 668 ("externally managed") on recent
# Debian/Ubuntu and Homebrew Python, and makes the install self-contained.
VENV_DIR="$SCRIPT_DIR/.venv"
if [[ ! -d "$VENV_DIR" ]]; then
  echo "==> Creating Python venv at $VENV_DIR"
  python3 -m venv "$VENV_DIR"
fi
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
echo "==> Installing Python dependencies into venv"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

# ── Step 5: internal frontend (built into frontend/dist/) ───────────────
echo "==> Building internal frontend"
(cd frontend && npm install && npm run build)

# ── Step 6: C&T frontend (sibling directory) ────────────────────────────
CT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)/customsandtaxriskmanagemensystem"
if [[ ! -d "$CT_DIR" ]]; then
  echo "==> Cloning C&T frontend to $CT_DIR"
  git clone https://github.com/jcvdschrieck/customsandtaxriskmanagemensystem.git "$CT_DIR"
fi
echo "==> Installing C&T frontend dependencies"
(cd "$CT_DIR" && npm install)

# ── Step 7: generate .env files ─────────────────────────────────────────
echo "==> Writing $CT_DIR/.env"
cat > "$CT_DIR/.env" <<EOF
VITE_API_BASE_URL=http://localhost:${BACKEND_PORT}
EOF

echo "==> Writing vat_fraud_detection/.env"
cat > "$SCRIPT_DIR/vat_fraud_detection/.env" <<EOF
LM_STUDIO_BASE_URL=${LM_STUDIO_URL}/v1
LM_STUDIO_MODEL=${LM_STUDIO_MODEL}
EOF

# ── Step 8: seed databases ──────────────────────────────────────────────
echo "==> Seeding databases"
python seed_databases.py

echo ""
echo "✅ Install complete."
echo ""
echo "Next steps:"
echo "  1. (Optional) Install LM Studio from https://lmstudio.ai and start its"
echo "     local server with the model '${LM_STUDIO_MODEL}' on ${LM_STUDIO_URL}."
echo "     Without it, the VAT Fraud Detection Agent returns 'uncertain'."
echo ""
echo "  2. (Optional, ~5 min) Build the RAG knowledge base so the agent can"
echo "     cite Irish VAT legislation:"
echo "       (cd vat_fraud_detection && python3 build_knowledge_base.py --minilm-only)"
echo ""
echo "  3. Launch everything:"
echo "       ./run.sh"
