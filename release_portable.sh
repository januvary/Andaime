#!/bin/bash
# ============================================
# SISTEMAS - Portable Release Script
# Builds the full portable SISTEMAS distribution
# (all apps) via build_portable.sh, zips it,
# tags the Andaime repo, and creates a GitHub
# Release with the artifact.
#
# Usage:
#   ./release_portable.sh            # version prompted
#   ./release_portable.sh 1.0.0 "Notes"
# ============================================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

cleanup() {
    exit_code=$?
    if [ "$exit_code" -ne 0 ] && [ -z "$1" ]; then
        echo ""
        echo -e "${RED}Script exited with error (code $exit_code).${NC}"
    fi
    if [ -z "$1" ]; then
        read -rp "Press Enter to close..."
    fi
    exit "$exit_code"
}
trap 'cleanup' EXIT

if [ -z "$1" ]; then
    read -rp "Version (e.g. 1.0.0): " VERSION
    if [ -z "$VERSION" ]; then
        echo -e "${RED}[ERROR]${NC} Version is required."
        exit 1
    fi
    read -rp "Notes [optional]: " NOTES
    NOTES="${NOTES:-Release v${VERSION}}"
else
    VERSION="$1"
    NOTES="${2:-Release v${VERSION}}"
fi
TAG="v${VERSION}"
REPO="januvary/andaime"

if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo -e "${RED}[ERROR]${NC} Version must be semver (e.g. 1.0.0)"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_PORTABLE="$SCRIPT_DIR/build_portable.sh"
DIST_DIR="$SCRIPT_DIR/dist"
SISTEMAS="$DIST_DIR/SISTEMAS"
ZIP_NAME="SISTEMAS-${TAG}-portable.zip"
ZIP_PATH="/tmp/${ZIP_NAME}"

cd "$SCRIPT_DIR" || { echo -e "${RED}[ERROR]${NC} Cannot cd to $SCRIPT_DIR"; exit 1; }

echo -e "${YELLOW}============================================${NC}"
echo -e "${YELLOW}SISTEMAS - Portable Release ${TAG}${NC}"
echo -e "${YELLOW}============================================${NC}"
echo ""

echo "[1/7] Checking for uncommitted changes..."
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

if git tag -l "$TAG" | grep -q "$TAG"; then
    echo -e "${RED}[ERROR]${NC} Tag ${TAG} already exists."
    exit 1
fi

if gh release view "$TAG" -R "$REPO" &>/dev/null; then
    echo -e "${RED}[ERROR]${NC} Release ${TAG} already exists on GitHub."
    exit 1
fi

echo -e "  ${GREEN}Clean working tree.${NC}"
echo ""

echo "[2/7] Building portable SISTEMAS distribution (all apps)..."
if [ ! -f "$BUILD_PORTABLE" ]; then
    echo -e "${RED}[ERROR]${NC} build_portable.sh not found at $BUILD_PORTABLE"
    exit 1
fi
bash "$BUILD_PORTABLE" --app all
echo ""

if [ ! -f "$SISTEMAS/bap.exe" ] || [ ! -f "$SISTEMAS/emissor.exe" ]; then
    echo -e "${RED}[ERROR]${NC} Build failed - launchers missing in $SISTEMAS."
    exit 1
fi

echo "[3/7] Bumping version to ${VERSION}..."
VERSION_FILE="$SCRIPT_DIR/pyproject.toml"
if [ ! -f "$VERSION_FILE" ]; then
    echo -e "${RED}[ERROR]${NC} Version file not found: $VERSION_FILE"
    exit 1
fi
sed -i "s/^version = .*/version = \"${VERSION}\"/" "$VERSION_FILE"
git add "$VERSION_FILE" apps/
git commit -m "Bump version to ${TAG}"
echo -e "  ${GREEN}pyproject.toml + apps/${NC} -> ${TAG}"
echo ""

echo "[4/7] Packaging (thin payload)..."
rm -f "$ZIP_PATH"
cd "$DIST_DIR"
zip -r "$ZIP_PATH" SISTEMAS/ -q \
    -x "SISTEMAS/python/*" \
       "SISTEMAS/apps/*"
ZIP_SIZE=$(du -sh "$ZIP_PATH" | cut -f1)
echo -e "  ${GREEN}${ZIP_NAME}${NC}: $ZIP_SIZE"
echo ""

echo "[5/7] Creating tag ${TAG}..."
git tag "$TAG"
git push origin "$TAG" 2>/dev/null || echo -e "  ${YELLOW}Warning: could not push tag (no remote?)${NC}"
echo ""

echo "[6/7] Creating GitHub release..."
gh release create "$TAG" "$ZIP_PATH" \
    --repo "$REPO" \
    --title "$TAG" \
    --notes "$NOTES"
echo ""

echo "[7/7] Squashing dist history (main)..."
CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
SQUASH_BRANCH="__release_sync"
git branch -D "$SQUASH_BRANCH" 2>/dev/null || true
git checkout -b "$SQUASH_BRANCH"
git reset --soft "$(git rev-list --max-parents=0 HEAD)"
git commit -m "SISTEMAS ${TAG}" >/dev/null
git push origin "$SQUASH_BRANCH:$CURRENT_BRANCH" --force
git checkout "$CURRENT_BRANCH"
git branch -D "$SQUASH_BRANCH" 2>/dev/null || true
echo -e "  ${GREEN}$CURRENT_BRANCH${NC} squashed to ${TAG}"
echo ""

echo -e "${GREEN}Done!${NC} $ZIP_SIZE uploaded to:"
echo "  https://github.com/$REPO/releases/tag/$TAG"
