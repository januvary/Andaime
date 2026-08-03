#!/bin/bash
# ============================================
# SISTEMAS — Single-App Release Script
#
# Builds a standalone Python-style distribution
# for one app, tags the app's GitHub repo, and
# creates a GitHub Release with payload + update
# zips.
#
# Usage:
#   ./release_app.sh rac                 # prompted
#   ./release_app.sh rac 1.2.3 "Notes"
# ============================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/build_lib.sh"

# --- Parse args / interactive menu ---
APP_TARGET="${1:-}"

show_menu() {
    echo "SISTEMAS — Release"
    echo ""
    echo "  0) All apps"
    local i=1
    APP_KEYS=()
    for key in bap emissor negativas rac; do
        local DISPLAY
        DISPLAY=$(app_field "${APPS[$key]}" 5)
        echo "  $i) $DISPLAY"
        APP_KEYS+=("$key")
        ((i++))
    done
    echo ""
}

if [ -z "$APP_TARGET" ] || [ -z "${APPS[$APP_TARGET]+x}" ]; then
    show_menu
    read -rp "Select [0-$(( ${#APP_KEYS[@]} ))]: " choice

    if ! [[ "$choice" =~ ^[0-9]+$ ]] || (( choice < 0 || choice > ${#APP_KEYS[@]} )); then
        echo "Invalid selection."
        exit 1
    fi

    # Prompt for shared version/notes once (used for single app or all apps).
    read -rp "Version (e.g. 1.0.0): " VERSION
    if [ -z "$VERSION" ]; then
        echo -e "${RED}[ERROR]${NC} Version is required."
        exit 1
    fi
    read -rp "Notes [optional]: " NOTES
    NOTES="${NOTES:-Release v${VERSION}}"

    if [[ "$choice" == "0" ]]; then
        echo ""
        for key in "${APP_KEYS[@]}"; do
            bash "$0" "$key" "$VERSION" "$NOTES"
        done
        exit 0
    fi

    APP_TARGET="${APP_KEYS[$((choice-1))]}"
fi

APP_INFO="${APPS[$APP_TARGET]}"
APP_MODULE=$(app_field "$APP_INFO" 1)
APP_REPO=$(app_field "$APP_INFO" 2)
APP_SRC=$(app_field "$APP_INFO" 3)
APP_DISPLAY=$(app_field "$APP_INFO" 5)

TAG_PREFIX="v"

# --- Version ---
DSTAMP=$(date +"%y.%m.%d-%H%M")
TAG="${DSTAMP}"

if [[ ! "$TAG" =~ ^[0-9]{2}\.[0-9]{2}\.[0-9]{2}-[0-9]{4}$ ]]; then
    echo -e "${RED}[ERROR]${NC} Failed to compute datestamp."
    exit 1
fi

if [ -z "${2:-}" ]; then
    echo -e "${YELLOW}${APP_DISPLAY} — Release ${TAG}${NC}"
    echo ""
    read -rp "Notes [optional]: " NOTES
    NOTES="${NOTES:-Release ${TAG}}"
else
    NOTES="${2:-Release ${TAG}}"
fi

# --- Paths ---
BUILD_APP="$SCRIPT_DIR/build_app.sh"
DIST_DIR="$SCRIPT_DIR/dist"
STAGE="$DIST_DIR/$APP_MODULE"
PAYLOAD_ZIP="$STAGE/${APP_MODULE}-${TAG}-payload.zip"
APP_UPDATE_ZIP="$STAGE/${APP_MODULE}-${TAG}-app-update.zip"
USER_ZIP="$STAGE/${APP_MODULE}-${TAG}.zip"
LAUNCHER_EXE="$STAGE/${APP_MODULE}.exe"
VERSION_FILE="$STAGE/VERSION"

echo ""
echo -e "${YELLOW}============================================${NC}"
echo -e "${YELLOW}${APP_DISPLAY} — Release ${TAG}${NC}"
echo -e "${YELLOW}  repo: ${APP_REPO}${NC}"
echo -e "${YELLOW}============================================${NC}"
echo ""

# ============================================
# Check for uncommitted changes in source repo
# ============================================
echo "Checking source repo for uncommitted changes..."
cd "$APP_SRC"
if ! git diff --quiet || ! git diff --cached --quiet; then
    echo -e "${YELLOW}[WARN]${NC} Uncommitted changes in $APP_SRC:"
    git status --short
    echo ""
    read -rp "Commit all changes before releasing? [y/N]: " COMMIT_CHOICE
    if [[ "$COMMIT_CHOICE" =~ ^[Yy]$ ]]; then
        read -rp "Commit message: " COMMIT_MSG
        COMMIT_MSG="${COMMIT_MSG:-pre-release commit}"
        git add -A
        git commit -m "$COMMIT_MSG"
        echo -e "  ${GREEN}Committed.${NC}"
    else
        echo -e "${RED}[ERROR]${NC} Cannot release with uncommitted changes."
        exit 1
    fi
fi

if git tag -l "$TAG" | grep -q "$TAG"; then
    echo -e "${RED}[ERROR]${NC} Tag ${TAG} already exists in $APP_REPO."
    exit 1
fi

if gh release view "$TAG" -R "$APP_REPO" &>/dev/null; then
    echo -e "${RED}[ERROR]${NC} Release ${TAG} already exists on GitHub."
    exit 1
fi

echo -e "  ${GREEN}Clean working tree.${NC}"
echo ""

# ============================================
# 2. Set datestamp in source repo
# ============================================
echo "[2/6] Setting datestamp in source repo..."
VERSION_FILE_SRC="$APP_SRC/src/__init__.py"
if [ -f "$VERSION_FILE_SRC" ]; then
    sed -i "s/^__version__ = .*/__version__ = \"${TAG}\"/" "$VERSION_FILE_SRC"
    git add "$VERSION_FILE_SRC"
    git commit -m "Bump version to ${TAG}" >/dev/null
    echo -e "  ${GREEN}src/__init__.py${NC} → ${TAG}"
else
    echo -e "  ${YELLOW}[WARN]${NC} src/__init__.py not found, skipping version bump"
fi
echo ""

# ============================================
# Build
# ============================================
echo "Building standalone distribution..."
if [ ! -f "$BUILD_APP" ]; then
    echo -e "${RED}[ERROR]${NC} build_app.sh not found at $BUILD_APP"
    exit 1
fi
bash "$BUILD_APP" "$APP_MODULE"
echo ""

if [ ! -f "$USER_ZIP" ]; then
    echo -e "${RED}[ERROR]${NC} Build failed — user zip not found."
    exit 1
fi

# ============================================
# 4. Read datestamp + hashes from VERSION file
# ============================================
echo "[4/6] Reading build metadata..."
DSTAMP=""
RUNTIME_HASH=""
APP_HASH=""
if [ -f "$VERSION_FILE" ]; then
    DSTAMP=$(head -1 "$VERSION_FILE" 2>/dev/null | tr -d '\r')
    RUNTIME_HASH=$(grep "^runtime:" "$VERSION_FILE" | sed 's/runtime: *//' || echo "")
    APP_HASH=$(grep "^${APP_MODULE}:" "$VERSION_FILE" | sed "s/${APP_MODULE}: *//" || echo "")
fi
echo -e "  Datestamp:  ${DSTAMP:-unknown}"
echo -e "  Runtime:    ${RUNTIME_HASH:-unknown}"
echo -e "  ${APP_MODULE}:     ${APP_HASH:-unknown}"
echo ""

# ============================================
# Commit apps/ sync in Andaime repo
# ============================================
echo "Committing app sync..."
cd "$SCRIPT_DIR"
APPS_DIR="$SCRIPT_DIR/apps/$APP_MODULE"
if [ -d "$APPS_DIR" ]; then
    git add "$APPS_DIR/"
    if ! git diff --cached --quiet; then
        git commit -m "Sync $APP_DISPLAY ${TAG}" >/dev/null
        echo -e "  ${GREEN}apps/$APP_MODULE/${NC} synced"
    else
        echo -e "  ${YELLOW}No changes to commit${NC}"
    fi
fi
echo ""

# ============================================
# 6. Tag + push source repo
# ============================================
echo "[6/6] Tagging + pushing source repo..."
cd "$APP_SRC"
if git tag -l "$TAG" | grep -q "$TAG"; then
    echo -e "${RED}[ERROR]${NC} Tag ${TAG} already exists in $APP_REPO."
    exit 1
fi
git tag "$TAG"
git push origin "$TAG" 2>/dev/null || echo -e "  ${YELLOW}Warning: could not push tag (no remote?)${NC}"
echo ""

# ============================================
# Create GitHub release (app repo only)
# ============================================
echo "Creating GitHub release..."

USER_SIZE=$(du -sh "$USER_ZIP" | cut -f1)

gh release create "$TAG" \
    "$USER_ZIP" \
    --repo "$APP_REPO" \
    --title "$TAG" \
    --notes "Baixe e extraia \`$(basename "$USER_ZIP")\`"
echo -e "  ${GREEN}Done!${NC} $USER_SIZE → $APP_REPO"
echo "  https://github.com/$APP_REPO/releases/tag/$TAG"
echo ""
echo "  Run release_portable.sh to publish the andaime release (payload + updates)."
