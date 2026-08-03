#!/bin/bash
# ============================================
# SISTEMAS — Portable Distribution Builder
#
# Assembles a portable Windows dist from the current separate repos.
#
# Produces:
#   dist/SISTEMAS/
#   ├── python/           (portable Python + all deps in site-packages)
#   ├── apps/
#   │   ├── bap/          (src/ copied, imports renamed src.→bap.)
#   │   ├── emissor/      (src/ copied, imports renamed src.→emissor.)
#   │   ├── rac/          (src/ copied, imports renamed src.→rac.)
#   │   └── negativas/    (src/ copied, imports renamed src.→negativas.)
#   ├── BAP/bap.exe       (per-app folders: <DISPLAY>/<app>.exe + data/)
#   ├── Emissor/emissor.exe
#   ├── RAC/rac.exe
#   ├── Negativas/negativas.exe
#   ├── dist.zip          (payload for %LOCALAPPDATA% extraction)
#   ├── VERSION           (version string + runtime hash)
#   └── shortcuts.bat     (convenience shortcuts for network share)
#
# Usage:
#   ./build_portable.sh                # build all apps
#   ./build_portable.sh --app bap     # build only BAP
#   ./build_portable.sh --skip-deps   # skip Wine pip
#   ./build_portable.sh --no-prune    # skip size optimisation
# ============================================

# Source build library
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/build_lib.sh"

# --- Paths ---
DIST="$ANDAIME_REPO/dist"
STAGE="$DIST/SISTEMAS"

# --- Args ---
APP_TARGET="all"
SKIP_DEPS=0
NO_PRUNE=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --app)      APP_TARGET="$2"; shift 2 ;;
        --skip-deps) SKIP_DEPS=1; shift ;;
        --no-prune)  NO_PRUNE=1;  shift ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

# --- Build flags ---
declare -A BUILD_FLAGS
case "$APP_TARGET" in
    all) for app_key in "${!APPS[@]}"; do BUILD_FLAGS[$app_key]=1; done ;;
    *)   if [ -n "${APPS[$APP_TARGET]+x}" ]; then
            BUILD_FLAGS["$APP_TARGET"]=1
         else
            echo "Invalid --app: $APP_TARGET (use ${!APPS[@]}|all)"
            exit 1
         fi ;;
esac

# ============================================
echo "============================================"
echo "SISTEMAS — Portable Build"
echo "  apps: $APP_TARGET"
echo "  deps: $([ $SKIP_DEPS -eq 1 ] && echo 'skip' || echo 'install')"
echo "  prune: $([ $NO_PRUNE -eq 1 ] && echo 'skip' || echo 'yes')"
echo "============================================"

# ============================================
# Prerequisites
# ============================================
APPS_TO_CHECK=""
for app_key in "${!BUILD_FLAGS[@]}"; do
    APPS_TO_CHECK="$APPS_TO_CHECK $app_key"
done
check_prerequisites "portable" "$APPS_TO_CHECK" || exit 1

# ============================================
# Sync app sources
# ============================================
for app_key in "${!BUILD_FLAGS[@]}"; do
    if [ "${BUILD_FLAGS[$app_key]}" -eq 1 ]; then
        echo -e "\n${YELLOW}Syncing $app_key source -> apps/$app_key/${NC}"
        sync_app "$app_key" || exit 1
    fi
done

# ============================================
# Prepare Wine Python dependencies
# ============================================
prepare_wine_python "$SKIP_DEPS"

# ============================================
# Clean + create stage
# ============================================
echo -e "\n${YELLOW}Cleaning previous build...${NC}"
rm -rf "$STAGE"
mkdir -p "$STAGE/python" "$STAGE/apps"

cp "$ANDAIME_REPO/launchers/shortcuts.bat" "$STAGE/"
ok "shortcuts.bat copied"

# VERSION file - datestamp + runtime hash + per-app hashes
DSTAMP=$(datestamp_version)
RUNTIME_HASH=$(compute_runtime_hash)
echo "${DSTAMP}" > "$STAGE/VERSION"
echo "runtime: ${RUNTIME_HASH}" >> "$STAGE/VERSION"
ok "VERSION: $DSTAMP (runtime: $RUNTIME_HASH)"

for app_key in "${!BUILD_FLAGS[@]}"; do
    if [ "${BUILD_FLAGS[$app_key]}" -eq 1 ]; then
        app_hash=$(compute_app_hash "$app_key")
        echo "$app_key: $app_hash" >> "$STAGE/VERSION"
        ok "$app_key hash: $app_hash"
    fi
done

ANDAIME_HASH=$(compute_andaime_hash)
echo "andaime: ${ANDAIME_HASH}" >> "$STAGE/VERSION"
ok "andaime hash: $ANDAIME_HASH"

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
for app_key in "${!BUILD_FLAGS[@]}"; do
    if [ "${BUILD_FLAGS[$app_key]}" -eq 1 ]; then
        echo -e "\n${YELLOW}Staging $app_key${NC}"
        stage_app "$app_key" "$STAGE"
    fi
done

# ============================================
# Prune (size optimisation)
# ============================================
prune_python "$STAGE" "$NO_PRUNE"

# ============================================
# Compile bytecode
# ============================================
APPS_TO_COMPILE=""
for app_key in "${!BUILD_FLAGS[@]}"; do
    if [ "${BUILD_FLAGS[$app_key]}" -eq 1 ]; then
        APPS_TO_COMPILE="$APPS_TO_COMPILE $app_key"
    fi
done
compile_bytecode "$STAGE" "$APPS_TO_COMPILE"

# ============================================
# Compile launchers (per-app folders)
# ============================================
echo -e "\n${YELLOW}Compiling launchers...${NC}"
for app_key in "${!BUILD_FLAGS[@]}"; do
    if [ "${BUILD_FLAGS[$app_key]}" -eq 1 ]; then
        app_info="${APPS[$app_key]}"
        module=$(app_field "$app_info" 1)
        icon=$(app_field "$app_info" 4)
        display=$(app_field "$app_info" 5)

APP_DIR="$STAGE/$display"
mkdir -p "$APP_DIR/data"

LAUNCHER_PATH="$APP_DIR/${module}.exe"
        compile_launcher "$LAUNCHER_PATH" "$icon" "portable" "$app_info"
    fi
done

# ============================================
# Create dist.zip
# ============================================
echo -e "\n${YELLOW}Creating dist.zip...${NC}"

ZIP_PATH="$STAGE/dist.zip"
rm -f "$ZIP_PATH"
cd "$STAGE"

# Create zip with python/, apps/, VERSION at the root (no SISTEMAS/ prefix)
zip -r "$ZIP_PATH" "python/" "apps/" "VERSION" -q \
    -x "python/__pycache__" \
       "apps/*/__pycache__"

ZIP_SIZE=$(du -sh "$ZIP_PATH" | cut -f1)
ok "dist.zip: $ZIP_SIZE"

# ============================================
# Report
# ============================================
echo -e "\n${YELLOW}Build complete!${NC}"
echo ""
echo "Output:"
echo "  $STAGE/"
echo ""
echo "Contents:"
( cd "$STAGE" && find . -maxdepth 2 -type d | sort | sed 's/^/  /' )
echo ""
TOTAL=$(du -sh "$STAGE" | cut -f1)
PY_FINAL=$(du -sh "$STAGE/python" | cut -f1)
echo -e "  ${GREEN}Total:${NC}   $TOTAL"
echo -e "  python/: $PY_FINAL"
for app_key in "${!BUILD_FLAGS[@]}"; do
    if [ "${BUILD_FLAGS[$app_key]}" -eq 1 ]; then
        app_info="${APPS[$app_key]}"
        name=$(app_field "$app_info" 5)
        APP_SIZE=$(du -sh "$STAGE/apps/$(app_name "$app_info")" | cut -f1)
        echo -e "  $name/:  $APP_SIZE"
    fi
done
echo ""
echo "Launchers:"
for app_key in "${!BUILD_FLAGS[@]}"; do
    if [ "${BUILD_FLAGS[$app_key]}" -eq 1 ]; then
        app_info="${APPS[$app_key]}"
        module=$(app_field "$app_info" 1)
        display=$(app_field "$app_info" 5)
        echo "  $STAGE/$display/${module}.exe"
    fi
done
echo ""

echo -e "  ${GREEN}dist.zip:${NC} $ZIP_SIZE"
echo ""

echo -e "${GREEN}Done.${NC}"
echo "  Network share: copy dist.zip + VERSION + shortcuts.bat + per-app folders (BAP/, RAC/, …) to the share root"
echo "  Standalone:    copy SISTEMAS/ folder and double-click the .exe"