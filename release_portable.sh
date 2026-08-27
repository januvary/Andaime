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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/build_lib.sh"

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

echo "[1/6] Checking andaime repo for uncommitted changes..."
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

echo -e "  ${GREEN}Andaime repo clean.${NC}"
echo ""

# ============================================
# Commit + push app source repos
# ============================================
echo "[2/6] Committing + pushing app source repos..."
for app_key in "${APP_ORDER[@]}"; do
    app_info="${APPS[$app_key]}"
    src=$(app_field "$app_info" 3)
    display=$(app_field "$app_info" 5)

    if [ ! -d "$src" ]; then
        echo -e "  ${YELLOW}!${NC} $display: source not found ($src), skipping"
        continue
    fi

    if ! git -C "$src" rev-parse --git-dir >/dev/null 2>&1; then
        echo -e "  ${YELLOW}!${NC} $display: not a git repo, skipping"
        continue
    fi

    cd "$src"
    if ! git diff --quiet || ! git diff --cached --quiet; then
        git add -A
        git commit -m "Sync before release ${TAG}" >/dev/null
        echo -e "  ${GREEN}✓${NC} $display: committed uncommitted changes"
    fi

    git push origin HEAD >/dev/null 2>&1 \
        && echo -e "  ${GREEN}✓${NC} $display: pushed" \
        || echo -e "  ${YELLOW}!${NC} $display: push failed (no remote?)"
done
echo ""

cd "$SCRIPT_DIR"

echo "[3/6] Building portable SISTEMAS distribution (all apps)..."
BUILD_PORTABLE="$SCRIPT_DIR/build_portable.sh"
if [ ! -f "$BUILD_PORTABLE" ]; then
    err "build_portable.sh not found at $BUILD_PORTABLE"
    exit 1
fi
bash "$BUILD_PORTABLE" --app all
echo ""

if [ ! -f "$SISTEMAS/dist.zip" ] || [ ! -f "$SISTEMAS/VERSION" ]; then
    echo -e "${RED}[ERROR]${NC} Build failed — dist.zip or VERSION missing in $SISTEMAS."
    exit 1
fi

# Re-read the datestamp actually built into VERSION so the release tag
# matches it exactly — the build recomputes its own DSTAMP and can cross
# a minute boundary mid-build (observed tag/VERSION drift of 1 minute).
TAG="$(head -1 "$SISTEMAS/VERSION" | tr -d '\r')"
if [[ ! "$TAG" =~ ^[0-9]{2}\.[0-9]{2}\.[0-9]{2}-[0-9]{4}$ ]]; then
    echo -e "${RED}[ERROR]${NC} Invalid datestamp in built VERSION: '${TAG}'"
    exit 1
fi
ok "Release tag aligned with VERSION: ${TAG}"

# ============================================
# Guard: every expected hash must be present in VERSION.
# A missing/absent hash makes the launcher/Python treat the release as an
# update forever (hash-compare, missing = update needed). Catch it here so
# a malformed VERSION is never published.
# ============================================
echo "[4/6] Validating VERSION manifest..."
MISSING_HASH=0
for check_key in runtime andaime ${APP_ORDER[@]}; do
    if ! grep -q "^${check_key}:" "$SISTEMAS/VERSION"; then
        echo -e "  ${RED}✗${NC} VERSION is missing key: ${check_key}"
        MISSING_HASH=1
    fi
done
if grep -E ": *[[:space:]]*(unknown)?[[:space:]]*$" "$SISTEMAS/VERSION"; then
    echo -e "  ${RED}✗${NC} VERSION contains a blank/unknown hash."
    MISSING_HASH=1
else
    echo -e "  ${GREEN}✓${NC} VERSION hashes present and non-empty"
fi
if [ "$MISSING_HASH" -eq 1 ]; then
    echo -e "${RED}[ERROR]${NC} Refusing to release a malformed VERSION."
    exit 1
fi
ok "VERSION manifest OK"
echo ""

echo "[5/6] Creating release assets..."

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

echo "[6/6] Creating GitHub release on $REPO..."
gh release create "$TAG" \
    "$PORTABLE_ASSET" \
    "$PAYLOAD_ASSET" \
    "$APP_UPDATE_ASSET" \
    "$SISTEMAS/VERSION" \
    --repo "$REPO" \
    --title "$TAG" \
    --notes "SISTEMAS ${TAG}"
echo ""

# ============================================
# Commit + push andaime repo
# ============================================
echo "Committing + pushing andaime repo..."
cd "$SCRIPT_DIR"

git add -A
if ! git diff --cached --quiet; then
    git commit -m "Release ${TAG}" >/dev/null
fi

CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
git push origin "$CURRENT_BRANCH" 2>/dev/null \
    && echo -e "  ${GREEN}Pushed to origin/${CURRENT_BRANCH}${NC}" \
    || echo -e "  ${YELLOW}!${NC} Push failed (no remote?)"

echo ""
echo -e "${GREEN}Done!${NC}"
echo "  https://github.com/$REPO/releases/tag/$TAG"