#!/bin/bash
# ============================================
# SISTEMAS — Portable Release Script
#
# Builds the full portable SISTEMAS distribution
# (all apps) via build_portable.sh, then uploads
# dist.zip + VERSION to januvary/andaime.
#
# Usage:
#   ./release_portable.sh
# ============================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_PORTABLE="$SCRIPT_DIR/build_portable.sh"
DIST_DIR="$SCRIPT_DIR/dist"
SISTEMAS="$DIST_DIR/SISTEMAS"
REPO="januvary/andaime"

DSTAMP=$(date +"%y.%m.%d-%H%M")
TAG="$DSTAMP"

if [[ ! "$TAG" =~ ^[0-9]{2}\.[0-9]{2}\.[0-9]{2}-[0-9]{4}$ ]]; then
    echo -e "${RED}[ERROR]${NC} Failed to compute datestamp."
    exit 1
fi

cd "$SCRIPT_DIR" || { echo -e "${RED}[ERROR]${NC} Cannot cd to $SCRIPT_DIR"; exit 1; }

echo -e "${YELLOW}============================================${NC}"
echo -e "${YELLOW}SISTEMAS - Portable Release ${TAG}${NC}"
echo -e "${YELLOW}============================================${NC}"
echo ""

echo "[1/4] Checking for uncommitted changes..."
if ! git diff --quiet || ! git diff --cached --quiet; then
    echo -e "${YELLOW}[WARN]${NC} Uncommitted changes detected:"
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

echo -e "  ${GREEN}Clean working tree.${NC}"
echo ""

echo "[2/4] Building portable SISTEMAS distribution (all apps)..."
if [ ! -f "$BUILD_PORTABLE" ]; then
    echo -e "${RED}[ERROR]${NC} build_portable.sh not found at $BUILD_PORTABLE"
    exit 1
fi
bash "$BUILD_PORTABLE" --app all
echo ""

if [ ! -f "$SISTEMAS/dist.zip" ] || [ ! -f "$SISTEMAS/VERSION" ]; then
    echo -e "${RED}[ERROR]${NC} Build failed — dist.zip or VERSION missing in $SISTEMAS."
    exit 1
fi

echo "[3/5] Creating release assets..."

# Rename dist.zip → {TAG}-payload.zip (updater matches "payload" in name)
PAYLOAD_ASSET="/tmp/${TAG}-payload.zip"
cp "$SISTEMAS/dist.zip" "$PAYLOAD_ASSET"

# Create app-update.zip (apps/ + andaime/ + VERSION, no python/)
APP_UPDATE_ASSET="/tmp/${TAG}-app-update.zip"
cd "$SISTEMAS"
zip -r "$APP_UPDATE_ASSET" "apps/" "VERSION" -q \
    -x "apps/*/__pycache__"
cd "$SISTEMAS/python/Lib/site-packages"
zip -r "$APP_UPDATE_ASSET" "andaime/" -q

# Create portable distribution zip (launchers + empty data/ + VERSION + shortcuts)
# Admins download this to set up a share; each exe downloads payload from GitHub on first run.
PORTABLE_ASSET="/tmp/${TAG}.zip"

# Ensure data dirs exist and are empty (remove any Wine test data)
for app_dir in RAC Negativas Emissor BAP; do
    mkdir -p "$SISTEMAS/$app_dir/data"
    find "$SISTEMAS/$app_dir/data" -mindepth 1 -delete 2>/dev/null || true
done

cd "$DIST_DIR"
zip -r "$PORTABLE_ASSET" \
    "SISTEMAS/RAC/" "SISTEMAS/Negativas/" "SISTEMAS/Emissor/" "SISTEMAS/BAP/" \
    "SISTEMAS/VERSION" "SISTEMAS/shortcuts.bat" -q

echo "[4/5] Creating GitHub release on $REPO..."
gh release create "$TAG" \
    "$PORTABLE_ASSET" \
    "$PAYLOAD_ASSET" \
    "$APP_UPDATE_ASSET" \
    --repo "$REPO" \
    --title "$TAG" \
    --notes "$(cat "$SISTEMAS/VERSION")"

echo ""
echo -e "${GREEN}Done!${NC}"
echo "  https://github.com/$REPO/releases/tag/$TAG"