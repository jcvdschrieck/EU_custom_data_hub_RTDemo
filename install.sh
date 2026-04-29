#!/usr/bin/env bash
# EU Custom Data Hub — one-shot installer for macOS / Linux.
#
# What it does (idempotent):
#   1. Installs Python 3.11+ and Node.js 18+ via brew / apt if missing.
#   2. Installs Python deps (pip) and Node deps (npm) for both frontends.
#   3. Builds the internal Vite frontend into frontend/dist/.
#   4. Writes customsandtaxriskmanagemensystem/.env and
#      vat_fraud_detection/.env from config.env.
#   5. Seeds the four SQLite databases.
#
# Note: both vat_fraud_detection/ and customsandtaxriskmanagemensystem/
# are vendored — their sources ship inside this repo as plain tree
# content. A single "git clone" brings the whole stack; no submodule
# init, no separate C&T frontend clone needed.
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
LLM_PROVIDER=lmstudio
LLM_MODEL=mistralai/mistral-7b-instruct-v0.3
LLM_API_KEY=
LLM_BASE_URL=
LM_STUDIO_URL=http://localhost:1234
LM_STUDIO_MODEL=mistralai/mistral-7b-instruct-v0.3
AZURE_OPENAI_ENDPOINT=
AZURE_OPENAI_DEPLOYMENT=
AZURE_OPENAI_API_VERSION=2024-02-15-preview
# Override from config.env if present.
if [[ -f "$SCRIPT_DIR/config.env" ]]; then
  # shellcheck disable=SC1091
  source "$SCRIPT_DIR/config.env"
fi

# Mask the API key when echoing back the config.
key_display="(unset)"
if [[ -n "$LLM_API_KEY" ]]; then
  key_display="****${LLM_API_KEY: -4}"
fi
echo "── Config ───────────────────────────────────────────────────────"
echo "  BACKEND_PORT     = $BACKEND_PORT"
echo "  CT_FRONTEND_PORT = $CT_FRONTEND_PORT"
echo "  LLM_PROVIDER     = $LLM_PROVIDER"
echo "  LLM_MODEL        = $LLM_MODEL"
echo "  LLM_API_KEY      = $key_display"
[[ -n "$LLM_BASE_URL" ]] && echo "  LLM_BASE_URL     = $LLM_BASE_URL"
if [[ "$LLM_PROVIDER" == "lmstudio" ]]; then
  echo "  LM_STUDIO_URL    = $LM_STUDIO_URL"
fi
if [[ "$LLM_PROVIDER" == "azure" ]]; then
  echo "  AZURE_ENDPOINT   = $AZURE_OPENAI_ENDPOINT"
  echo "  AZURE_DEPLOYMENT = $AZURE_OPENAI_DEPLOYMENT"
fi
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

# ── Detect packaged-mode artefacts ──────────────────────────────────────
# build_release.sh ships a `.packaged` marker plus pre-fetched wheels,
# pre-built frontend dists, a pre-warmed HF cache and pre-seeded DBs.
# When present, install.sh skips the corresponding online steps.
PACKAGED=false
if [[ -f "$SCRIPT_DIR/.packaged" ]]; then
  PACKAGED=true
  echo "==> Packaged mode detected (.packaged found)"
fi

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
if [[ -d "$SCRIPT_DIR/wheels" ]] && ls "$SCRIPT_DIR/wheels"/*.whl >/dev/null 2>&1; then
  echo "==> Installing Python dependencies (offline, from wheels/)"
  python -m pip install --upgrade --no-index --find-links "$SCRIPT_DIR/wheels" pip || true
  python -m pip install --no-index --find-links "$SCRIPT_DIR/wheels" \
                         -r requirements.txt
else
  echo "==> Installing Python dependencies from PyPI"
  python -m pip install --upgrade pip
  python -m pip install -r requirements.txt
fi

# ── Step 5: internal frontend (built into frontend/dist/) ───────────────
if [[ -f "$SCRIPT_DIR/frontend/dist/index.html" ]]; then
  echo "==> Internal frontend already built (frontend/dist/) — skipping"
else
  echo "==> Building internal frontend"
  (cd frontend && npm install && npm run build)
fi

# ── Step 6: C&T frontend (vendored subdirectory) ────────────────────────
# When packaged, the C&T dashboard ships pre-built into dist/ and
# is served by run.sh via Python's http.server (no node at runtime).
# In dev mode (no dist/), install npm deps so `npm run dev` works.
CT_DIR="$SCRIPT_DIR/customsandtaxriskmanagemensystem"
if [[ -f "$CT_DIR/dist/index.html" ]]; then
  echo "==> C&T dashboard already built (customsandtaxriskmanagemensystem/dist/) — skipping npm install"
else
  echo "==> Installing C&T frontend dependencies"
  (cd "$CT_DIR" && npm install)
fi

# ── Step 7: generate .env files ─────────────────────────────────────────
echo "==> Writing $CT_DIR/.env"
cat > "$CT_DIR/.env" <<EOF
VITE_API_BASE_URL=http://localhost:${BACKEND_PORT}
EOF

echo "==> Writing vat_fraud_detection/.env"
{
  echo "# Generated by install.sh from config.env — do not commit."
  echo "LLM_PROVIDER=${LLM_PROVIDER}"
  echo "LLM_MODEL=${LLM_MODEL}"
  [[ -n "$LLM_API_KEY"  ]] && echo "LLM_API_KEY=${LLM_API_KEY}"
  [[ -n "$LLM_BASE_URL" ]] && echo "LLM_BASE_URL=${LLM_BASE_URL}"
  # LM Studio specifics
  echo "LM_STUDIO_BASE_URL=${LM_STUDIO_URL}/v1"
  echo "LM_STUDIO_MODEL=${LM_STUDIO_MODEL}"
  # Provider-specific cloud keys mirrored from LLM_API_KEY when set,
  # so users who paste the key into config.env's LLM_API_KEY don't
  # also have to set OPENAI_API_KEY / ANTHROPIC_API_KEY / etc.
  if [[ -n "$LLM_API_KEY" ]]; then
    case "$LLM_PROVIDER" in
      openai)    echo "OPENAI_API_KEY=${LLM_API_KEY}" ;;
      anthropic) echo "ANTHROPIC_API_KEY=${LLM_API_KEY}" ;;
      azure)     echo "AZURE_OPENAI_API_KEY=${LLM_API_KEY}" ;;
    esac
  fi
  if [[ "$LLM_PROVIDER" == "azure" ]]; then
    echo "AZURE_OPENAI_ENDPOINT=${AZURE_OPENAI_ENDPOINT}"
    echo "AZURE_OPENAI_DEPLOYMENT=${AZURE_OPENAI_DEPLOYMENT}"
    echo "AZURE_OPENAI_API_VERSION=${AZURE_OPENAI_API_VERSION}"
  fi
} > "$SCRIPT_DIR/vat_fraud_detection/.env"

# ── Step 7b: warm the HF embedder cache ─────────────────────────────────
# Downloads the all-MiniLM-L6-v2 SentenceTransformer weights (~90 MB)
# into the local HF cache so the VAT Fraud Detection agent can load the
# model in offline mode at runtime. When packaged, the cache ships
# pre-warmed under models/hf-cache/ — we point HF_HOME there in the
# generated .env so the agent reads from the bundled copy.
if [[ -d "$SCRIPT_DIR/models/hf-cache" ]]; then
  echo "==> HF cache pre-shipped (models/hf-cache/) — appending HF_HOME to .env"
  echo "HF_HOME=$SCRIPT_DIR/models/hf-cache" \
       >> "$SCRIPT_DIR/vat_fraud_detection/.env"
else
  echo "==> Warming the Hugging Face embedder cache (~90 MB, one-off)"
  python scripts/warm_hf_cache.py
fi

# ── Step 8: seed databases ──────────────────────────────────────────────
if ls "$SCRIPT_DIR/data"/*.db >/dev/null 2>&1; then
  echo "==> Databases already pre-seeded (data/*.db) — skipping"
else
  echo "==> Seeding databases"
  python seed_databases.py
fi

echo ""
echo "✅ Install complete."
echo ""
echo "Active LLM configuration:"
case "$LLM_PROVIDER" in
  lmstudio)
    echo "  Provider: LM Studio (local) — ${LM_STUDIO_URL}"
    echo "  Model:    ${LLM_MODEL}"
    echo "  → Install LM Studio from https://lmstudio.ai, load this model,"
    echo "    and click Start Server in the Developer tab before running."
    echo "    Without LM Studio the agent returns 'uncertain'."
    ;;
  openai)
    echo "  Provider: OpenAI cloud"
    echo "  Model:    ${LLM_MODEL}"
    echo "  API key:  $key_display"
    ;;
  anthropic)
    echo "  Provider: Anthropic Claude"
    echo "  Model:    ${LLM_MODEL}"
    echo "  API key:  $key_display"
    ;;
  azure)
    echo "  Provider: Azure OpenAI"
    echo "  Endpoint: ${AZURE_OPENAI_ENDPOINT}"
    echo "  Deploy:   ${AZURE_OPENAI_DEPLOYMENT}"
    echo "  API key:  $key_display"
    ;;
esac
echo ""
echo "Next steps:"
echo "  1. (Optional, ~5 min) Build the RAG knowledge base so the agent can"
echo "     cite Irish VAT legislation:"
echo "       (cd vat_fraud_detection && python3 build_knowledge_base.py --minilm-only)"
echo ""
echo "  2. Launch everything:"
echo "       ./run.sh"
