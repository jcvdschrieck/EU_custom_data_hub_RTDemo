#!/usr/bin/env bash
# build_release.sh — package the EU Custom Data Hub demo into a single
# self-contained ZIP suitable for SharePoint distribution.
#
# What it does:
#   1. Reads the version from the top-level VERSION file.
#   2. Copies the project tree into a staging directory, excluding
#      developer artefacts (.git, .venv, __pycache__, node_modules).
#   3. Pre-fetches Python wheels for the host platform into wheels/.
#   4. Pre-builds the internal Vite frontend into frontend/dist/.
#   5. Pre-builds the C&T dashboard into customsandtaxriskmanagemensystem/dist/.
#   6. Pre-warms the Hugging Face embedder cache into models/hf-cache/.
#   7. Pre-seeds the four SQLite databases into data/.
#   8. Drops a `.packaged` marker so install.sh knows to use the
#      bundled artefacts instead of fetching from the network.
#   9. Zips the staging dir → releases/EU-Custom-Data-Hub-vX.Y.Z-<os>.zip.
#
# Run from the project root:    ./scripts/build_release.sh
#
# Maintainers: build on each target OS to produce the per-platform zip
# (Python wheels are platform-specific). Upload all three zips to
# SharePoint so end users can pick the matching one.
set -euo pipefail

PROJ_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJ_ROOT"

if [[ ! -f VERSION ]]; then
  echo "!! VERSION file missing at $PROJ_ROOT/VERSION" >&2
  exit 1
fi
VERSION=$(tr -d '[:space:]' < VERSION)

# Detect host OS for the zip filename.
case "$(uname -s)" in
  Darwin*)  OS_TAG=macos ;;
  Linux*)   OS_TAG=linux ;;
  *)        OS_TAG=$(uname -s | tr '[:upper:]' '[:lower:]') ;;
esac

PKG_NAME="EU-Custom-Data-Hub-v${VERSION}-${OS_TAG}"
STAGE_DIR="$PROJ_ROOT/build/${PKG_NAME}"
RELEASE_DIR="$PROJ_ROOT/releases"
ZIP_PATH="$RELEASE_DIR/${PKG_NAME}.zip"

echo "── Build target ────────────────────────────────────────────────"
echo "  Version:  $VERSION"
echo "  OS tag:   $OS_TAG"
echo "  Stage:    $STAGE_DIR"
echo "  Output:   $ZIP_PATH"
echo "────────────────────────────────────────────────────────────────"

# ── Step 1: clean stage ────────────────────────────────────────────────
rm -rf "$STAGE_DIR"
mkdir -p "$STAGE_DIR" "$RELEASE_DIR"

# ── Step 2: copy source ────────────────────────────────────────────────
echo "==> Copying source tree (excluding dev artefacts)"
EXCLUDES=(
  --exclude=.git
  --exclude=.venv
  --exclude=node_modules
  --exclude=__pycache__
  --exclude='*.pyc'
  --exclude=.pytest_cache
  --exclude=.DS_Store
  --exclude=build
  --exclude=releases
  --exclude='*.bak'
  --exclude='Context/Screenshot*'
  --exclude='*.log'
)
rsync -a "${EXCLUDES[@]}" --exclude='.env' "$PROJ_ROOT/" "$STAGE_DIR/"

# ── Step 3: pre-fetch Python wheels ────────────────────────────────────
echo "==> Pre-fetching Python wheels for $OS_TAG"
mkdir -p "$STAGE_DIR/wheels"
# Use the system / dev Python so the wheels match the runtime Python's
# tag triplet exactly. End-user installers must use the same major.minor.
python3 -m pip download \
  --dest "$STAGE_DIR/wheels" \
  --requirement "$PROJ_ROOT/requirements.txt" \
  --quiet || {
    echo "!! pip download failed — package will require online install" >&2
    rm -rf "$STAGE_DIR/wheels"
  }

# ── Step 4: build internal frontend ────────────────────────────────────
if [[ -d "$PROJ_ROOT/frontend" ]]; then
  echo "==> Building internal frontend"
  (cd "$PROJ_ROOT/frontend" && npm install --silent && npm run build --silent)
  rm -rf "$STAGE_DIR/frontend/dist"
  cp -R "$PROJ_ROOT/frontend/dist" "$STAGE_DIR/frontend/dist"
fi

# ── Step 5: build C&T dashboard ────────────────────────────────────────
CT_DIR="$PROJ_ROOT/customsandtaxriskmanagemensystem"
if [[ -d "$CT_DIR" ]]; then
  echo "==> Building C&T dashboard"
  (cd "$CT_DIR" && npm install --silent && npm run build --silent)
  rm -rf "$STAGE_DIR/customsandtaxriskmanagemensystem/dist"
  cp -R "$CT_DIR/dist" "$STAGE_DIR/customsandtaxriskmanagemensystem/dist"
fi

# ── Step 6: pre-warm HF embedder cache ─────────────────────────────────
echo "==> Pre-warming Hugging Face embedder cache (~90 MB)"
WARM_SCRIPT="$PROJ_ROOT/scripts/warm_hf_cache.py"
if [[ -f "$WARM_SCRIPT" ]]; then
  STAGED_HF="$STAGE_DIR/models/hf-cache"
  mkdir -p "$STAGED_HF"
  HF_HOME="$STAGED_HF" python3 "$WARM_SCRIPT" || {
    echo "!! HF cache warm failed — package will fetch at install time" >&2
    rm -rf "$STAGE_DIR/models"
  }
fi

# ── Step 7: pre-seed databases ─────────────────────────────────────────
echo "==> Seeding databases into staging"
mkdir -p "$STAGE_DIR/data"
cp -R "$PROJ_ROOT/Context" "$STAGE_DIR/" 2>/dev/null || true
(cd "$STAGE_DIR" && python3 seed_databases.py >/dev/null 2>&1) || {
  echo "!! Database seed failed — package will seed at install time" >&2
  rm -f "$STAGE_DIR/data"/*.db
}

# ── Step 8: marker so install.sh detects bundled artefacts ─────────────
cat > "$STAGE_DIR/.packaged" <<EOF
version=$VERSION
os=$OS_TAG
built_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF

# ── Step 9: zip ────────────────────────────────────────────────────────
echo "==> Compressing to $ZIP_PATH"
rm -f "$ZIP_PATH"
(cd "$PROJ_ROOT/build" && zip -rq "$ZIP_PATH" "$PKG_NAME")

SIZE_MB=$(du -m "$ZIP_PATH" | cut -f1)
echo ""
echo "✅ Built $ZIP_PATH (${SIZE_MB} MB)"
echo ""
echo "Contents summary:"
echo "  Source:           always present"
echo "  Python wheels:    $(test -d "$STAGE_DIR/wheels" && echo yes || echo no)"
echo "  Frontend dist:    $(test -d "$STAGE_DIR/frontend/dist" && echo yes || echo no)"
echo "  C&T dist:         $(test -d "$STAGE_DIR/customsandtaxriskmanagemensystem/dist" && echo yes || echo no)"
echo "  HF cache:         $(test -d "$STAGE_DIR/models/hf-cache" && echo yes || echo no)"
echo "  Pre-seeded DBs:   $(ls "$STAGE_DIR/data"/*.db >/dev/null 2>&1 && echo yes || echo no)"
echo ""
echo "Upload $ZIP_PATH to SharePoint and reference it from INSTALL.md."
