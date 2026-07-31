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
#   ├── bap.exe           (launchers — try GitHub first, fallback to dist.zip)
#   ├── emissor.exe
#   ├── rac.exe
#   ├── negativas.exe
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
# 1. Prerequisites
# ============================================
APPS_TO_CHECK=""
for app_key in "${!BUILD_FLAGS[@]}"; do
    APPS_TO_CHECK="$APPS_TO_CHECK $app_key"
done
check_prerequisites "portable" "$APPS_TO_CHECK" || exit 1

# ============================================
# 2. Sync app sources
# ============================================
for app_key in "${!BUILD_FLAGS[@]}"; do
    if [ "${BUILD_FLAGS[$app_key]}" -eq 1 ]; then
        step "2x" "Syncing $app_key source -> apps/$app_key/..."
        sync_app "$app_key" || exit 1
    fi
done

# ============================================
# 3. Prepare Wine Python dependencies
# ============================================
prepare_wine_python "$SKIP_DEPS"

# ============================================
# 4. Clean + create stage
# ============================================
step "3" "Cleaning previous build..."
rm -rf "$DIST"
mkdir -p "$STAGE/python" "$STAGE/apps"

cp "$ANDAIME_REPO/launchers/shortcuts.bat" "$STAGE/"
ok "shortcuts.bat copied"

# VERSION file - andaime version + runtime hash (not app version)
PYPROJECT_VER=$(grep '^version = ' "$ANDAIME_REPO/pyproject.toml" 2>/dev/null | sed 's/version = "//;s/"//')
RUNTIME_HASH=$(compute_runtime_hash)
echo "${PYPROJECT_VER:-unknown}" > "$STAGE/VERSION"
ok "VERSION written (${PYPROJECT_VER:-unknown})"

# ============================================
# 5. Copy Windows Python tree
# ============================================
copy_python "$STAGE"

# ============================================
# 6. Copy andaime chassis
# ============================================
copy_andaime "$STAGE"

# ============================================
# 7. Stage app code
# ============================================
for app_key in "${!BUILD_FLAGS[@]}"; do
    if [ "${BUILD_FLAGS[$app_key]}" -eq 1 ]; then
        step "7x" "Staging $app_key..."
        stage_app "$app_key" "$STAGE"
    fi
done

# ============================================
# 8. Prune (size optimisation)
# ============================================
prune_python "$STAGE" "$NO_PRUNE"

# ============================================
# 9. Compile bytecode
# ============================================
APPS_TO_COMPILE=""
for app_key in "${!BUILD_FLAGS[@]}"; do
    if [ "${BUILD_FLAGS[$app_key]}" -eq 1 ]; then
        APPS_TO_COMPILE="$APPS_TO_COMPILE $app_key"
    fi
done
compile_bytecode "$STAGE" "$APPS_TO_COMPILE"

# ============================================
# 10. Compile launchers
# ============================================
step "10" "Compiling launchers..."
for app_key in "${!BUILD_FLAGS[@]}"; do
    if [ "${BUILD_FLAGS[$app_key]}" -eq 1 ]; then
        app_info="${APPS[$app_key]}"
        module=$(app_field "$app_info" 1)
        icon=$(app_field "$app_info" 4)

        LAUNCHER_PATH="$STAGE/${module}.exe"
        compile_launcher "$LAUNCHER_PATH" "$icon" "portable" "$app_info"
    fi
done

# ============================================
# 11. Create dist.zip
# ============================================
step "11" "Creating dist.zip..."

ZIP_PATH="$STAGE/dist.zip"
rm -f "$ZIP_PATH"
cd "$DIST"

zip -r "$ZIP_PATH" SISTEMAS/ -q \
    -x "SISTEMAS/dist.zip" \
       "SISTEMAS/shortcuts.bat"

# Remove .exe files from zip (they should remain in the share root)
for app_key in "${!BUILD_FLAGS[@]}"; do
    if [ "${BUILD_FLAGS[$app_key]}" -eq 1 ]; then
        app_info="${APPS[$app_key]}"
        module=$(app_field "$app_info" 1)
        zip -d "$ZIP_PATH" "SISTEMAS/${module}.exe" >/dev/null 2>&1 || true
    fi
done

ZIP_SIZE=$(du -sh "$ZIP_PATH" | cut -f1)
ok "dist.zip: $ZIP_SIZE"

# ============================================
# 12. Report
# ============================================
step "12" "Build complete!"
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
        echo "  $STAGE/${module}.exe"
    fi
done
echo ""

echo -e "  ${GREEN}dist.zip:${NC} $ZIP_SIZE"
echo ""

echo -e "${GREEN}Done.${NC}"
echo "  Network share: copy *.exe + dist.zip + VERSION + shortcuts.bat to the share root"
echo "  Standalone:    copy SISTEMAS/ folder and double-click the .exe"