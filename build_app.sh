#!/bin/bash
# ============================================
# SISTEMAS — Single-App Standalone Builder
#
# Builds ONE app as a standalone Python-style
# distribution (embedded Python + app + andaime).
#
# Produces:
#   dist/<app>/
#   ├── python/              (pruned embedded CPython)
#   ├── apps/<app>/          (app code, src→<app> renamed)
#   ├── VERSION              (app version + runtime hash)
#   ├── launcher.exe         (compiled with GitHub repo info)
#   ├── <app>-v<X>.zip           (user download: <DISPLAY>/<app>.exe + data/)
#   ├── <app>-v<X>-payload.zip   (full payload for first install)
#   └── <app>-v<X>-update.zip    (app code only for auto-updater)
#
# Usage:
#   ./build_app.sh rac                # build RAC
#   ./build_app.sh emissor            # build Emissor
#   ./build_app.sh rac --skip-deps    # skip Wine pip install
#   ./build_app.sh rac --no-prune     # skip size optimisation
# ============================================

# Source build library
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/build_lib.sh"

# --- Args ---
APP_TARGET=""
SKIP_DEPS=0
NO_PRUNE=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-deps) SKIP_DEPS=1; shift ;;
        --no-prune)  NO_PRUNE=1;  shift ;;
        --help|-h)
            echo "Usage: ./build_app.sh <app> [--skip-deps] [--no-prune]"
            echo "Apps: ${!APPS[@]}"
            exit 0 ;;
        *) APP_TARGET="$1"; shift ;;
    esac
done

# --- Determine apps to build ---
declare -A BUILD_FLAGS
if [ -z "$APP_TARGET" ] || [ -z "${APPS[$APP_TARGET]+x}" ]; then
    # Interactive menu
    echo "SISTEMAS — Standalone Builder"
    echo ""
    echo "  0) All apps"
    i=1
    APP_KEYS=()
    for key in bap emissor negativas rac; do
        DISPLAY=$(app_field "${APPS[$key]}" 5)
        echo "  $i) $DISPLAY"
        APP_KEYS+=("$key")
        ((i++))
    done
    echo ""
    read -rp "Select [0-$((i-1))]: " choice

    if [[ "$choice" == "0" ]]; then
        echo ""
        for key in "${APP_KEYS[@]}"; do
            bash "$0" "$key" $([ $SKIP_DEPS -eq 1 ] && echo --skip-deps) $([ $NO_PRUNE -eq 1 ] && echo --no-prune)
        done
        exit 0
    fi

    if ! [[ "$choice" =~ ^[0-9]+$ ]] || (( choice < 1 || choice >= i )); then
        echo "Invalid selection."
        exit 1
    fi
    APP_TARGET="${APP_KEYS[$((choice-1))]}"
fi

BUILD_FLAGS["$APP_TARGET"]=1

APP_INFO="${APPS[$APP_TARGET]}"
APP_MODULE=$(app_field "$APP_INFO" 1)
APP_REPO=$(app_field "$APP_INFO" 2)
APP_SRC=$(app_field "$APP_INFO" 3)
APP_ICON=$(app_field "$APP_INFO" 4)
APP_DISPLAY=$(app_field "$APP_INFO" 5)

DIST="$ANDAIME_REPO/dist"
STAGE="$DIST/$APP_MODULE"

# ============================================
echo "============================================"
echo "SISTEMAS — Standalone Build: $APP_DISPLAY"
echo "  module: $APP_MODULE"
echo "  repo:   $APP_REPO"
echo "  deps:   $([ $SKIP_DEPS -eq 1 ] && echo 'skip' || echo 'install')"
echo "  prune:  $([ $NO_PRUNE -eq 1 ] && echo 'skip' || echo 'yes')"
echo "============================================"

# ============================================
# Prerequisites
# ============================================
check_prerequisites "standalone" "$APP_TARGET" || exit 1

# ============================================
# Sync app source
# ============================================
echo -e "\n${YELLOW}Syncing $APP_MODULE source...${NC}"
sync_app "$APP_MODULE" || exit 1

# ============================================
# Prepare Wine Python dependencies
# ============================================
prepare_wine_python "$SKIP_DEPS"

# ============================================
# Compute runtime hash
# ============================================
echo -e "\n${YELLOW}Computing runtime hash...${NC}"
RUNTIME_HASH=$(compute_runtime_hash)
ok "Runtime hash: $RUNTIME_HASH"

# ============================================
# 5. Read app version + compute hashes
# ============================================
STEP_NUM="5"
DSTAMP=$(datestamp_version)
ok "Datestamp: $DSTAMP"

APP_HASH=$(compute_app_hash "$APP_MODULE")
ok "App hash: $APP_HASH"

RUNTIME_HASH=$(compute_runtime_hash)
ok "Runtime hash: $RUNTIME_HASH"

# ============================================
# Clean + create stage
# ============================================
echo -e "\n${YELLOW}Creating stage...${NC}"
rm -rf "$STAGE"
mkdir -p "$STAGE/python" "$STAGE/apps"

# VERSION file: datestamp + runtime hash + app hash
echo -e "${DSTAMP}\nruntime: ${RUNTIME_HASH}\n${APP_MODULE}: ${APP_HASH}" > "$STAGE/VERSION"
ok "VERSION: $DSTAMP (runtime: $RUNTIME_HASH, $APP_MODULE: $APP_HASH)"

# ============================================
# Copy Windows Python tree
# ============================================
copy_python "$STAGE"

# ============================================
# Copy andaime chassis
# ============================================
copy_andaime "$STAGE"

# ============================================
# Stage app code
# ============================================
echo -e "\n${YELLOW}Staging app code...${NC}"
stage_app "$APP_MODULE" "$STAGE"

# ============================================
# Prune (size optimisation)
# ============================================
prune_python "$STAGE" "$NO_PRUNE"

# ============================================
# Compile bytecode
# ============================================
compile_bytecode "$STAGE" "$APP_MODULE"

# ============================================
# Compile launcher.exe
# ============================================
echo -e "\n${YELLOW}Compiling launcher.exe...${NC}"
LAUNCHER_PATH="$STAGE/${APP_MODULE}.exe"
compile_launcher "$LAUNCHER_PATH" "$APP_ICON" "standalone" "$APP_INFO"

# ============================================
# Create zips
# ============================================
echo -e "\n${YELLOW}Creating archives...${NC}"

TAG="$DSTAMP"

# --- Payload zip (full: python/ + apps/ + VERSION) ---
PAYLOAD_ZIP="$STAGE/${APP_MODULE}-${TAG}-payload.zip"
rm -f "$PAYLOAD_ZIP"
cd "$STAGE"
zip -r "$PAYLOAD_ZIP" "python/" "apps/" "VERSION" -q
PAYLOAD_SIZE=$(du -sh "$PAYLOAD_ZIP" | cut -f1)
ok "payload.zip: $PAYLOAD_SIZE"

# --- App update zip (app code only) ---
APP_UPDATE_ZIP="$STAGE/${APP_MODULE}-${TAG}-app-update.zip"
rm -f "$APP_UPDATE_ZIP"
cd "$STAGE"
zip -r "$APP_UPDATE_ZIP" \
    "apps/$APP_MODULE/" \
    "VERSION" -q
# Add andaime from site-packages
cd "$STAGE/python/Lib/site-packages"
zip -r "$APP_UPDATE_ZIP" "andaime/" -q
APP_UPDATE_SIZE=$(du -sh "$APP_UPDATE_ZIP" | cut -f1)
ok "app-update.zip: $APP_UPDATE_SIZE"

# --- User-facing zip (extract-and-run: <DISPLAY>/<app>.exe + data/) ---
USER_ZIP="$STAGE/${APP_MODULE}-${TAG}.zip"
WRAPPER="$STAGE/$APP_DISPLAY"
rm -f "$USER_ZIP"
rm -rf "$WRAPPER"
mkdir -p "$WRAPPER/data"
cp "$LAUNCHER_PATH" "$WRAPPER/${APP_MODULE}.exe"
cd "$STAGE"
zip -r "$USER_ZIP" "$APP_DISPLAY/" -q
USER_SIZE=$(du -sh "$USER_ZIP" | cut -f1)
ok "user zip: $USER_SIZE"

# ============================================
# Report
# ============================================
echo -e "\n${YELLOW}Build complete!${NC}"
echo ""
echo "Output: $STAGE/"
echo ""
echo "Artifacts:"
echo "  User zip:       $USER_ZIP ($USER_SIZE)"
echo "  Payload zip:    $PAYLOAD_ZIP ($PAYLOAD_SIZE)"
echo "  App update zip: $APP_UPDATE_ZIP ($APP_UPDATE_SIZE)"
echo ""
TOTAL=$(du -sh "$STAGE" | cut -f1)
echo -e "  ${GREEN}Total stage:${NC} $TOTAL"
echo ""
echo "To release:"
echo "  ./release_app.sh $APP_MODULE"