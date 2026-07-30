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
#   ├── launcher.exe         (compiled with embedded repo info)
#   ├── <app>-v<X>-payload.zip   (full payload for first install)
#   └── <app>-v<X>-update.zip    (app code only for auto-updater)
#
# Usage:
#   ./build_app.sh rac                # build RAC
#   ./build_app.sh emissor            # build Emissor
#   ./build_app.sh rac --skip-deps    # skip Wine pip install
#   ./build_app.sh rac --no-prune     # skip size optimisation
# ============================================

set -euo pipefail

# --- Paths ---
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ANDAIME_REPO="$SCRIPT_DIR"
WINE_PY_DIR="$HOME/.wine/drive_c/Python310"
WINE_PYTHON='C:\Python310\python.exe'

DIST="$ANDAIME_REPO/dist"

# --- App Registry ---
# Format: "module|repo|src_path|icon_path|display_name|app_folder"
declare -A APPS
APPS[bap]="bap|januvary/bap|$HOME/Projects/SS 54 - Vindication|$ANDAIME_REPO/launchers/icons/bap.ico|BAP|BAP"
APPS[emissor]="emissor|januvary/Emissor|$HOME/Projects/Emissor|$ANDAIME_REPO/launchers/icons/emissor.ico|Emissor|Emissor"
APPS[rac]="rac|januvary/RAC|$HOME/Projects/RAC - Registros Alto Custo|$ANDAIME_REPO/launchers/icons/rac.ico|RAC|RAC"
APPS[negativas]="negativas|januvary/negativas|$HOME/Projects/SISTEMA DE NEGATIVAS|$ANDAIME_REPO/launchers/icons/negativas.ico|Negativas|Negativas"

# Helpers
app_field() { echo "$1" | cut -d'|' -f"$2"; }

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

APP_INFO="${APPS[$APP_TARGET]}"
APP_MODULE=$(app_field "$APP_INFO" 1)
APP_REPO=$(app_field "$APP_INFO" 2)
APP_SRC=$(app_field "$APP_INFO" 3)
APP_ICON=$(app_field "$APP_INFO" 4)
APP_DISPLAY=$(app_field "$APP_INFO" 5)
APP_FOLDER=$(app_field "$APP_INFO" 6)

STAGE="$DIST/$APP_MODULE"

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'
step() { echo -e "\n${YELLOW}[$1]${NC} $2"; }
ok()   { echo -e "  ${GREEN}✓${NC} $1"; }
err()  { echo -e "  ${RED}✗${NC} $1"; }

# ============================================
echo "============================================"
echo "SISTEMAS — Standalone Build: $APP_DISPLAY"
echo "  module: $APP_MODULE"
echo "  repo:   $APP_REPO"
echo "  deps:   $([ $SKIP_DEPS -eq 1 ] && echo 'skip' || echo 'install')"
echo "  prune:  $([ $NO_PRUNE -eq 1 ] && echo 'skip' || echo 'yes')"
echo "============================================"

# ============================================
# 1. Prerequisites
# ============================================
step "1" "Checking prerequisites..."

if [ ! -d "$APP_SRC" ]; then
    err "Source not found: $APP_SRC"
    exit 1
fi

if [ ! -d "$WINE_PY_DIR" ]; then
    err "Wine Python not found: $WINE_PY_DIR"
    exit 1
fi

if ! command -v wine &>/dev/null; then
    err "Wine is not installed"
    exit 1
fi

if ! command -v x86_64-w64-mingw32-gcc &>/dev/null; then
    err "mingw64-gcc is not installed (needed to compile launcher)"
    echo "  Install with: sudo dnf install mingw64-gcc"
    exit 1
fi

ok "Source:     $APP_SRC"
ok "Andaime:    $ANDAIME_REPO"
ok "Wine Py:    $WINE_PY_DIR"
ok "mingw:      $(x86_64-w64-mingw32-gcc -dumpmachine)"

# ============================================
# 2. Sync app source → apps/<module>/
# ============================================
step "2" "Syncing $APP_MODULE source..."

APP_REPO_DIR="$ANDAIME_REPO/apps/$APP_MODULE"
rm -rf "$APP_REPO_DIR"
mkdir -p "$APP_REPO_DIR"

# Copy src/ contents
if [ -d "$APP_SRC/src" ]; then
    cp -r "$APP_SRC/src/"* "$APP_REPO_DIR/"
fi

# Copy main.py → __main__.py
if [ -f "$APP_SRC/main.py" ]; then
    cp "$APP_SRC/main.py" "$APP_REPO_DIR/__main__.py"
fi

# Copy icon
if [ -f "$APP_ICON" ]; then
    cp "$APP_ICON" "$APP_REPO_DIR/icon.ico"
fi

# Clean bytecode
find "$APP_REPO_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$APP_REPO_DIR" -type f -name "*.pyc" -delete 2>/dev/null || true

# Rename src. → <module>. imports
find "$APP_REPO_DIR" -name "*.py" -print0 | xargs -0 sed -i \
    -e "s/from src\\./from ${APP_MODULE}./g" \
    -e "s/from src import/from ${APP_MODULE} import/g" \
    -e "s/import src\\b/import ${APP_MODULE}/g"

# Remove legacy sys.path bootstrap lines
sed -i '/sys\.path\.insert(0, os\.path\.dirname/d' "$APP_REPO_DIR/__main__.py" 2>/dev/null || true

# Verify no stale imports
if grep -r "from src\.\|import src\b" "$APP_REPO_DIR/" --include="*.py" -q; then
    err "Stale 'src.' imports found:"
    grep -rn "from src\.\|import src\b" "$APP_REPO_DIR/" --include="*.py"
    exit 1
fi

ok "$APP_MODULE source synced → apps/$APP_MODULE/"

# Read app version
APP_VERSION=$(grep '__version__' "$APP_REPO_DIR/__init__.py" 2>/dev/null | head -1 | sed "s/.*['\"]\\(.*\\)['\"].*/\\1/" || echo "0.0.0")
if [ -z "$APP_VERSION" ]; then APP_VERSION="0.0.0"; fi
ok "Version: $APP_VERSION"

# ============================================
# 3. Prepare Wine Python dependencies
# ============================================
if [ $SKIP_DEPS -eq 0 ]; then
    step "3" "Preparing Wine Python dependencies..."

    wine "$WINE_PYTHON" -m pip install --upgrade \
        pyside6_essentials==6.7.3 pypdfium2 pypdf holidays typing_extensions \
        openpyxl pywin32 \
        google-api-python-client google-auth-oauthlib google-auth rapidfuzz \
        reportlab svglib python-dotenv requests \
        2>&1 | grep -v fixme | grep -i "successfully\|already\|Downloading\|Installing" | tail -10
    wine "$WINE_PYTHON" -m pip install --no-deps img2pdf \
        2>&1 | grep -v fixme | grep -i "successfully\|already\|Downloading" | tail -3

    ok "Wine Python deps ready"
else
    step "3" "Skipping dependency installation (--skip-deps)"
fi

# ============================================
# 4. Compute runtime hash
# ============================================
step "4" "Computing runtime hash..."
RUNTIME_HASH=$(wine "$WINE_PYTHON" -m pip freeze 2>/dev/null | sort | sha256sum | cut -c1-8)
ok "Runtime hash: $RUNTIME_HASH"

# ============================================
# 5. Clean + create stage
# ============================================
step "5" "Creating stage..."
rm -rf "$STAGE"
mkdir -p "$STAGE/python" "$STAGE/apps"

# VERSION file
echo -e "${APP_VERSION}\nruntime: ${RUNTIME_HASH}" > "$STAGE/VERSION"
ok "VERSION: $APP_VERSION (runtime: $RUNTIME_HASH)"

# ============================================
# 6. Copy Python tree
# ============================================
step "6" "Copying Windows Python tree..."
cp -r "$WINE_PY_DIR/"* "$STAGE/python/"

# Remove stale andaime editable install
rm -f "$STAGE/python/Lib/site-packages/__editable__.andaime-0.1.0.pth"
rm -f "$STAGE/python/Lib/site-packages/__editable___andaime_0_1_0_finder.py"
rm -rf "$STAGE/python/Lib/site-packages/andaime.egg-link"
rm -rf "$STAGE/python/Lib/site-packages/andaime-0.1.0.dist-info"

PY_SIZE=$(du -sh "$STAGE/python" | cut -f1)
ok "Python copied ($PY_SIZE)"

# sitecustomize.py (disable bytecode on network shares)
cp "$ANDAIME_REPO/launchers/sitecustomize.py" "$STAGE/python/Lib/site-packages/sitecustomize.py"
ok "sitecustomize.py copied"

# ============================================
# 7. Copy andaime chassis → site-packages
# ============================================
step "7" "Copying andaime chassis..."
cp -r "$ANDAIME_REPO/andaime" "$STAGE/python/Lib/site-packages/andaime"
cp "$ANDAIME_REPO/LICENSE" "$STAGE/python/Lib/site-packages/andaime/LICENSE"
ok "Chassis → site-packages/andaime/"

# ============================================
# 8. Stage app code
# ============================================
step "8" "Staging app code..."
mkdir -p "$STAGE/apps/$APP_MODULE"
cp -r "$APP_REPO_DIR/"* "$STAGE/apps/$APP_MODULE/"
cp "$ANDAIME_REPO/LICENSE" "$STAGE/apps/$APP_MODULE/LICENSE"
ok "App code → apps/$APP_MODULE/"

# ============================================
# 9. Prune (size optimisation)
# ============================================
if [ $NO_PRUNE -eq 0 ]; then
    step "9" "Pruning for size..."

    SP="$STAGE/python/Lib/site-packages"
    PYSIDE="$SP/PySide6"

    # --- PySide6: keep ONLY Core/Gui/Widgets ---
    find "$PYSIDE" -maxdepth 1 -name "Qt6*.dll" \
        ! -name "Qt6Core.dll" \
        ! -name "Qt6Gui.dll" \
        ! -name "Qt6Widgets.dll" \
        -delete

    for f in \
        Qt6WebEngineCore.dll opengl32sw.dll \
        avcodec-61.dll avformat-61.dll avutil-59.dll \
        swscale-8.dll swresample-5.dll \
        pyside6qml.abi3.dll \
        icudt73.dll \
        vcamp140.dll vccorlib140.dll concrt140.dll vcomp140.dll \
        vcruntime140.dll vcruntime140_1.dll; do
        rm -f "$PYSIDE/$f"
    done

    find "$PYSIDE" -maxdepth 1 -name "*.pyd" \
        ! -name "QtCore.pyd" \
        ! -name "QtGui.pyd" \
        ! -name "QtWidgets.pyd" \
        -delete

    for d in qml resources metatypes include typesystems \
             scripts glue QtAsyncio doc lib support; do
        rm -rf "$PYSIDE/$d"
    done

    find "$PYSIDE" -maxdepth 1 -name "*.exe" -delete
    find "$PYSIDE" -maxdepth 1 -name "*.pyi" -delete
    rm -f "$PYSIDE"/*.lib "$PYSIDE"/PySide6_*.json "$PYSIDE/_config.py" \
          "$PYSIDE/_git_pyside_version.py"
    ok "PySide6 stripped to Core/Gui/Widgets"

    # --- Qt plugins ---
    QT_PLUGINS="$PYSIDE/plugins"
    if [ -d "$QT_PLUGINS" ]; then
        find "$QT_PLUGINS" -maxdepth 1 -mindepth 1 -type d \
            ! -name "platforms" \
            ! -name "imageformats" \
            ! -name "iconengines" \
            -exec rm -rf {} +
        find "$QT_PLUGINS/platforms" -type f ! -name "qwindows.dll" -delete 2>/dev/null || true
        find "$QT_PLUGINS/imageformats" -type f ! -name "qjpeg.dll" ! -name "qpng.dll" ! -name "qico.dll" -delete 2>/dev/null || true
        find "$QT_PLUGINS/iconengines" -type f ! -name "qsvgicon.dll" -delete 2>/dev/null || true
        ok "Qt plugins whitelisted"
    fi

    # --- Qt translations ---
    QT_TRANS="$PYSIDE/translations"
    if [ -d "$QT_TRANS" ]; then
        find "$QT_TRANS" -type f ! -name "qtbase_pt*" ! -name "qt_pt*" -delete
        ok "Qt translations pruned"
    fi

    # --- google-api discovery cache ---
    GCACHE="$SP/googleapiclient/discovery_cache/documents"
    if [ -d "$GCACHE" ]; then
        find "$GCACHE" -maxdepth 1 -type f ! -name "gmail.v1.json" ! -name "drive.v3.json" -delete
        ok "Google discovery cache trimmed"
    fi

    # --- holidays: keep only Brazil ---
    HOL="$SP/holidays"
    if [ -d "$HOL/countries" ]; then
        find "$HOL/countries" -maxdepth 1 -type f -name "*.py" \
            ! -name "__init__.py" ! -name "brazil.py" -delete
        cat > "$HOL/countries/__init__.py" <<'PYEOF'
from holidays.countries.brazil import Brazil, BR, BRA  # noqa: F401
PYEOF
        rm -rf "$HOL/financial"
        sed -i '/from holidays.financial import \*/d' "$HOL/__init__.py" 2>/dev/null || true
        sed -i '/EntityLoader.load("financial", globals())/d' "$HOL/__init__.py" 2>/dev/null || true
        ok "holidays trimmed to Brazil"
    fi

    # --- Remove build-tool packages ---
    for pkg in pip setuptools wheel _distutils_hack \
               pyinstaller PyInstaller pyinstaller-hooks-contrib _pyinstaller_hooks_contrib \
               pikepdf pikepdf.libs pikepdf-*.dist-info \
               pythonwin customtkinter darkdetect PyWin32.chm \
               pillow Pillow-*.dist-info PIL \
               lxml lxml-*.dist-info \
               cryptography cryptography-*.dist-info; do
        rm -rf "$SP/$pkg"
    done
    rm -f "$SP/distutils-precedence.pth"
    ok "Build tools removed"

    # --- Remove Tcl/Tk ---
    rm -rf "$STAGE/python/tcl" "$STAGE/python/Lib/tkinter" "$SP/_tkinter"
    rm -f "$STAGE/python/DLLs/tcl86t.dll" "$STAGE/python/DLLs/tk86t.dll"
    ok "Tcl/Tk removed"

    # --- Remove shiboken6 duplicate DLLs ---
    SHIBOKEN="$SP/shiboken6"
    if [ -d "$SHIBOKEN" ]; then
        for f in vcruntime140.dll vcruntime140_1.dll msvcp140.dll msvcp140_1.dll msvcp140_2.dll msvcp140_codecvt_ids.dll concrt140.dll; do
            rm -f "$SHIBOKEN/$f"
        done
        ok "Shiboken6 runtime DLLs removed"
    fi

    # --- Stdlib trim ---
    rm -rf "$STAGE/python/Doc" "$STAGE/python/Tools"
    find "$STAGE/python/Lib" -type d -name "test" -exec rm -rf {} + 2>/dev/null || true
    rm -rf "$STAGE/python/Lib/idlelib" "$STAGE/python/Lib/ensurepip"
    rm -rf "$STAGE/python/Lib/include" "$STAGE/python/Lib/libs" "$STAGE/python/Scripts"

    # --- Remove standalone python.exe (not needed for -m launches) ---
    rm -f "$STAGE/python/python.exe"
    rm -f "$STAGE/python/python3.dll"
    rm -f "$STAGE/python/NEWS.txt"

    # --- Aggressive stdlib: remove unused large modules ---
    rm -rf "$STAGE/python/Lib/asyncio"
    rm -rf "$STAGE/python/Lib/http"
    rm -rf "$STAGE/python/Lib/email"
    rm -rf "$STAGE/python/Lib/xml"
    rm -rf "$STAGE/python/Lib/xmlrpc"
    rm -rf "$STAGE/python/Lib/urllib"
    rm -rf "$STAGE/python/Lib/concurrent"
    rm -rf "$STAGE/python/Lib/logging"
    rm -rf "$STAGE/python/Lib/multiprocessing"
    rm -rf "$STAGE/python/Lib/unittest"
    rm -rf "$STAGE/python/Lib/distutils"
    rm -rf "$STAGE/python/Lib/lib2to3"
    rm -rf "$STAGE/python/Lib/pydoc_data"
    rm -rf "$STAGE/python/Lib/venv"
    rm -rf "$STAGE/python/Lib/turtledemo"
    rm -f "$STAGE/python/Lib/turtle.py"
    rm -rf "$STAGE/python/Lib/msilib"
    ok "Stdlib trimmed"
else
    step "9" "Skipping prune (--no-prune)"
fi

# ============================================
# 10. Compile bytecode
# ============================================
step "10" "Compiling bytecode..."
find "$STAGE" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

COMPILE_TARGETS=$(winepath -w "$STAGE/apps/$APP_MODULE" 2>/dev/null | tr -d '\r')
COMPILE_TARGETS="$COMPILE_TARGETS $(winepath -w "$STAGE/python/Lib/site-packages/andaime" 2>/dev/null | tr -d '\r')"

timeout 60 wine "$WINE_PYTHON" -m compileall -q $COMPILE_TARGETS 2>/dev/null | grep -v fixme || true
ok "App + chassis bytecode compiled"

# ============================================
# 11. Compile launcher.exe
# ============================================
step "11" "Compiling launcher.exe..."

compile_launcher() {
    local output="$1" icon="$2" repo="$3" module="$4" display="$5"
    local rc_dir
    rc_dir=$(mktemp -d)

    # comctl6 manifest
    cat > "$rc_dir/manifest.xml" <<'XML'
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">
  <assemblyIdentity version="1.0.0.0" name="SISTEMAS.Launcher"/>
  <dependency>
    <dependentAssembly>
      <assemblyIdentity type="win32" name="Microsoft.Windows.Common-Controls"
                        version="6.0.0.0" processorArchitecture="*"
                        publicKeyToken="6595b64144ccf1df" language="*"/>
    </dependentAssembly>
  </dependency>
</assembly>
XML

    if [ -n "$icon" ] && [ -f "$icon" ]; then
        cp "$icon" "$rc_dir/app.ico"
    fi

    {
        if [ -f "$rc_dir/app.ico" ]; then
            echo '1 ICON "app.ico"'
        fi
        echo '1 RT_MANIFEST "manifest.xml"'
    } > "$rc_dir/app.rc"

    x86_64-w64-mingw32-windres "$rc_dir/app.rc" "$rc_dir/app_res.o" 2>/dev/null

    x86_64-w64-mingw32-gcc -O2 -s -o "$output" \
        "$ANDAIME_REPO/launcher.c" "$rc_dir/app_res.o" \
        -DAPP_REPO="\"$repo\"" \
        -DAPP_MODULE="\"$module\"" \
        -DAPP_DISPLAY="\"$display\"" \
        -mwindows -static -lcomctl32 -lwininet

    rm -rf "$rc_dir"
}

LAUNCHER_PATH="$STAGE/${APP_MODULE}.exe"
compile_launcher "$LAUNCHER_PATH" "$APP_ICON" "$APP_REPO" "$APP_MODULE" "$APP_DISPLAY"
ok "launcher.exe compiled ($APP_REPO)"

# ============================================
# 12. Create zips
# ============================================
step "12" "Creating archives..."

TAG="v${APP_VERSION}"

# --- Payload zip (full: python/ + apps/ + VERSION) ---
PAYLOAD_ZIP="$STAGE/${APP_MODULE}-${TAG}-payload.zip"
rm -f "$PAYLOAD_ZIP"
cd "$STAGE"
zip -r "$PAYLOAD_ZIP" "python/" "apps/" "VERSION" -q
PAYLOAD_SIZE=$(du -sh "$PAYLOAD_ZIP" | cut -f1)
ok "payload.zip: $PAYLOAD_SIZE"

# --- Update zip (small: apps/<module>/ + andaime/ + VERSION) ---
UPDATE_ZIP="$STAGE/${APP_MODULE}-${TAG}-update.zip"
rm -f "$UPDATE_ZIP"
cd "$STAGE"
zip -r "$UPDATE_ZIP" \
    "apps/$APP_MODULE/" \
    "VERSION" -q
# Add andaime from site-packages
cd "$STAGE/python/Lib/site-packages"
zip -r "$UPDATE_ZIP" "andaime/" -q
UPDATE_SIZE=$(du -sh "$UPDATE_ZIP" | cut -f1)
ok "update.zip: $UPDATE_SIZE"

# ============================================
# 13. Report
# ============================================
step "13" "Build complete!"
echo ""
echo "Output: $STAGE/"
echo ""
echo "Artifacts:"
echo "  Launcher:     $STAGE/${APP_MODULE}.exe"
echo "  Payload zip:  $PAYLOAD_ZIP ($PAYLOAD_SIZE)"
echo "  Update zip:   $UPDATE_ZIP ($UPDATE_SIZE)"
echo ""
TOTAL=$(du -sh "$STAGE" | cut -f1)
echo -e "  ${GREEN}Total stage:${NC} $TOTAL"
echo ""
echo "To release:"
echo "  ./release_app.sh $APP_MODULE"
