#!/bin/bash
# ============================================
# SISTEMAS — Portable Distribution Builder
#
# Assembles a portable Windows dist from the current separate repos,
# WITHOUT merging them. Reads from:
#
#   ~/Projects/SS 54 - Vindication/   (BAP source + main.py)
#   ~/Projects/Emissor/                (Emissor source + main.py)
#   ~/Projects/RAC - Registros Alto Custo/   (RAC source + main.py)
#   ~/Projects/Andaime/andaime/        (shared chassis)
#   ~/.wine/drive_c/Python310/         (Windows Python 3.10)
#
# Produces:
#   dist/SISTEMAS/
#   ├── python/           (portable Python + all deps in site-packages)
#   ├── apps/
#   │   ├── bap/          (src/ copied, imports renamed src.→bap.)
#   │   └── emissor/      (src/ copied, imports renamed src.→emissor.)
#   │   └── rac/          (src/ copied, imports renamed src.→rac.)
#   ├── bap.exe           (thin launchers — find dist.zip + VERSION in own dir)
#   ├── emissor.exe
#   ├── rac.exe
#   ├── dist.zip          (payload for %LOCALAPPDATA% extraction)
#   └── VERSION           (version string for update detection)
#
# Usage:
#   ./build_portable.sh              # build both apps
#   ./build_portable.sh --app bap     # build only BAP
#   ./build_portable.sh --app emissor # build only Emissor
#   ./build_portable.sh --app rac     # build only RAC
#   ./build_portable.sh --skip-deps   # skip Wine pip (use as-is)
#   ./build_portable.sh --no-prune    # skip size optimisation
# ============================================

set -euo pipefail

# --- Paths ---
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# Original local repos (source of truth for app code)
SRC_BAP="$HOME/Projects/SS 54 - Vindication"
SRC_EMISSOR="$HOME/Projects/Emissor"
SRC_RAC="$HOME/Projects/RAC - Registros Alto Custo"
# Vendored copies committed into this repo (synced from the above)
BAP_REPO="$SCRIPT_DIR/apps/bap"
EMISSOR_REPO="$SCRIPT_DIR/apps/emissor"
RAC_REPO="$SCRIPT_DIR/apps/rac"
ANDAIME_REPO="$SCRIPT_DIR"
WINE_PY_DIR="$HOME/.wine/drive_c/Python310"
WINE_PYTHON='C:\Python310\python.exe'

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

BUILD_BAP=0
BUILD_EMISSOR=0
BUILD_RAC=0
case "$APP_TARGET" in
    bap)     BUILD_BAP=1 ;;
    emissor) BUILD_EMISSOR=1 ;;
    rac)     BUILD_RAC=1 ;;
    all)     BUILD_BAP=1; BUILD_EMISSOR=1; BUILD_RAC=1 ;;
    *)       echo "Invalid --app: $APP_TARGET (use bap|emissor|rac|all)"; exit 1 ;;
esac

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'
step() { echo -e "\n${YELLOW}[$1]${NC} $2"; }
ok()   { echo -e "  ${GREEN}✓${NC} $1"; }
err()  { echo -e "  ${RED}✗${NC} $1"; }

# Rename src. -> <pkg>. imports in all .py files (used by sync_app + staging)
rename_imports() {
    local pkg="$1" dir="$2"
    find "$dir" -name "*.py" -print0 | xargs -0 sed -i \
        -e "s/from src\\./from ${pkg}./g" \
        -e "s/from src import/from ${pkg} import/g" \
        -e "s/import src\\b/import ${pkg}/g"
}

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
step "1" "Checking prerequisites..."

for d in "$BAP_REPO" "$EMISSOR_REPO" "$ANDAIME_REPO" "$WINE_PY_DIR"; do
    if [ ! -d "$d" ]; then
        err "Not found: $d"
        exit 1
    fi
done

if ! command -v wine &>/dev/null; then
    err "Wine is not installed"
    exit 1
fi

if ! command -v x86_64-w64-mingw32-gcc &>/dev/null; then
    err "mingw64-gcc is not installed (needed to compile launchers)"
    echo "  Install with: sudo dnf install mingw64-gcc"
    exit 1
fi

WINE_VER=$(wine --version 2>&1 | head -1)
ok "Wine: $WINE_VER"
ok "mingw:    $(x86_64-w64-mingw32-gcc -dumpmachine)"
ok "BAP:       $BAP_REPO"
ok "Emissor:   $EMISSOR_REPO"
ok "Andaime:   $ANDAIME_REPO"
ok "Wine Py:   $WINE_PY_DIR"

# ============================================
# 1b. Sync app sources into committed apps/ dir
# ============================================
# Copy app code from the original local repos into apps/ so the result is
# committed to this repo (self-contained, no need to download dist). Mirrors
# the staging transforms (src.->pkg. rename, main.py->__main__.py, root= patch).
sync_app() {
    local pkg="$1" src="$2" dst="$3" icon="$4"
    rm -rf "$dst"
    mkdir -p "$dst"
    cp -r "$src/src/"* "$dst/"
    cp "$src/main.py" "$dst/__main__.py"
    cp "$icon" "$dst/icon.ico"
    rename_imports "$pkg" "$dst"
    if [ "$pkg" = "bap" ]; then
        sed -i '/sys\.path\.insert(0, os\.path\.dirname/d' "$dst/__main__.py"
        sed -i '1a from pathlib import Path' "$dst/__main__.py"
    fi
}

if [ $BUILD_BAP -eq 1 ]; then
    step "1b" "Syncing BAP source -> apps/bap/"
    if [ -d "$SRC_BAP" ]; then
        sync_app "bap" "$SRC_BAP" "$BAP_REPO" "$ANDAIME_REPO/launchers/icons/bap.ico"
        ok "apps/bap/ updated from $SRC_BAP"
    else
        echo -e "  ${YELLOW}[WARN]${NC} source dir not found: $SRC_BAP — building from committed apps/bap/"
    fi
fi
if [ $BUILD_EMISSOR -eq 1 ]; then
    step "1b" "Syncing Emissor source -> apps/emissor/"
    if [ -d "$SRC_EMISSOR" ]; then
        sync_app "emissor" "$SRC_EMISSOR" "$EMISSOR_REPO" "$ANDAIME_REPO/launchers/icons/emissor.ico"
        ok "apps/emissor/ updated from $SRC_EMISSOR"
    else
        echo -e "  ${YELLOW}[WARN]${NC} source dir not found: $SRC_EMISSOR — building from committed apps/emissor/"
    fi
fi
if [ $BUILD_RAC -eq 1 ]; then
    step "1b" "Syncing RAC source -> apps/rac/"
    if [ -d "$SRC_RAC" ]; then
        sync_app "rac" "$SRC_RAC" "$RAC_REPO" "$SRC_RAC/RAC.ico"
        ok "apps/rac/ updated from $SRC_RAC"
    else
        echo -e "  ${YELLOW}[WARN]${NC} source dir not found: $SRC_RAC — building from committed apps/rac/"
    fi
fi

# ============================================
# 2. Prepare Wine Python (install/clean deps)
# ============================================
if [ $SKIP_DEPS -eq 0 ]; then
    step "2" "Preparing Wine Python dependencies..."

    # NOTE: do NOT uninstall pyinstaller from the source Wine Python here —
    # the RAC PyInstaller build (build_windows.sh) shares this interpreter and
    # self-installs its own deps. The portable dist strips build tools from the
    # staged copy in the prune step (7) instead.

    # Install the correct dependency set.
    # Packages already present are skipped by pip; missing ones are fetched.
    # img2pdf is installed with --no-deps to avoid pulling pikepdf (8.8 MB)
    # which img2pdf only uses for optional PDF/A optimizations.
    wine "$WINE_PYTHON" -m pip install --upgrade \
        pyside6_essentials==6.7.3 pypdfium2 pypdf Pillow holidays typing_extensions \
        openpyxl pywin32 \
        google-api-python-client google-auth-oauthlib google-auth rapidfuzz \
        reportlab svglib python-dotenv requests \
        2>&1 | grep -v fixme | grep -i "successfully\|already\|Downloading\|Installing" | tail -10
    wine "$WINE_PYTHON" -m pip install --no-deps img2pdf \
        2>&1 | grep -v fixme | grep -i "successfully\|already\|Downloading" | tail -3

    ok "Wine Python deps ready"
else
    step "2" "Skipping dependency installation (--skip-deps)"
fi

# ============================================
# 3. Clean + create stage
# ============================================
step "3" "Cleaning previous build..."
rm -rf "$DIST"
mkdir -p "$STAGE/python" "$STAGE/apps"
ok "Stage: $STAGE"

cp "$ANDAIME_REPO/launchers/shortcuts.bat" "$STAGE/"
ok "shortcuts.bat copied"

# VERSION file (read by the smart launcher to detect updates)
PYPROJECT_VER=$(grep '^version = ' "$ANDAIME_REPO/pyproject.toml" | sed 's/version = "//;s/"//')
echo "${PYPROJECT_VER:-unknown}" > "$STAGE/VERSION"
ok "VERSION written (${PYPROJECT_VER:-unknown})"

# Third-party license pointer (GPL corresponding-source requirement) — lives
# inside python/ since it documents the bundled Python packages.
cp "$ANDAIME_REPO/THIRD_PARTY_LICENSES" "$STAGE/python/THIRD_PARTY_LICENSES"
ok "THIRD_PARTY_LICENSES copied to python/"

# GPLv3 LICENSE is copied alongside each shipped component after staging
# (apps/<app>/, site-packages/andaime) — see steps 6a/6b below.

# ============================================
# 4. Copy Python tree
# ============================================
step "4" "Copying Windows Python tree..."
cp -r "$WINE_PY_DIR/"* "$STAGE/python/"

# Remove the stale andaime editable install (points to old lowercase path).
# We'll drop a fresh snapshot into site-packages in step 5.
rm -f "$STAGE/python/Lib/site-packages/__editable__.andaime-0.1.0.pth"
rm -f "$STAGE/python/Lib/site-packages/__editable___andaime_0_1_0_finder.py"
rm -rf "$STAGE/python/Lib/site-packages/andaime.egg-link"
rm -rf "$STAGE/python/Lib/site-packages/andaime-0.1.0.dist-info"

PY_SIZE=$(du -sh "$STAGE/python" | cut -f1)
ok "Python copied ($PY_SIZE)"

# sitecustomize.py: disables bytecode caching (network-share .pyc staleness fix)
cp "$ANDAIME_REPO/launchers/sitecustomize.py" "$STAGE/python/Lib/site-packages/sitecustomize.py"
ok "sitecustomize.py copied (disables .pyc on network shares)"

# ============================================
# 5. Copy chassis into site-packages
# ============================================
step "5" "Copying andaime chassis..."
cp -r "$ANDAIME_REPO/andaime" "$STAGE/python/Lib/site-packages/andaime"
cp "$ANDAIME_REPO/LICENSE" "$STAGE/python/Lib/site-packages/andaime/LICENSE"
ok "Chassis → site-packages/andaime/ (+ LICENSE)"

# ============================================
# 6. Stage app(s)
# ============================================

# Compile launcher.c into <name>.exe, optionally embedding an .ico icon.
compile_launcher() {
    local output="$1" icon="$2"
    local rc_dir
    rc_dir=$(mktemp -d)

    # comctl6 manifest (enables themed controls + PBS_MARQUEE animation)
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
        echo '#define IDD_PROGRESS 100'
        echo '#define IDC_PROGRESS 101'
        echo 'IDD_PROGRESS DIALOG 10, 10, 340, 110'
        echo 'CAPTION "SISTEMAS"'
        echo 'FONT 9, "Segoe UI"'
        echo 'BEGIN'
        echo '    LTEXT "Instalando o SISTEMAS...", -1, 20, 24, 300, 20'
        echo '    LTEXT "Por favor, aguarde enquanto os arquivos sao copiados.", -1, 20, 46, 300, 20'
        echo '    CONTROL "", IDC_PROGRESS, "msctls_progress32", 0x00800008, 20, 78, 300, 16'
        echo 'END'
    } > "$rc_dir/app.rc"

    x86_64-w64-mingw32-windres "$rc_dir/app.rc" "$rc_dir/app_res.o" 2>/dev/null
    x86_64-w64-mingw32-gcc -O2 -s -o "$output" \
        "$ANDAIME_REPO/launcher.c" "$rc_dir/app_res.o" -mwindows -static -lcomctl32

    rm -rf "$rc_dir"
}

# --- BAP ---
if [ $BUILD_BAP -eq 1 ]; then
    step "6a" "Staging BAP..."
    mkdir -p "$STAGE/apps/bap"
    cp -r "$BAP_REPO/"* "$STAGE/apps/bap/"

    # Verify no stale src. imports remain
    if grep -r "from src\.\|import src\b" "$STAGE/apps/bap/" --include="*.py" -q; then
        err "Stale 'src.' imports found in BAP:"
        grep -rn "from src\.\|import src\b" "$STAGE/apps/bap/" --include="*.py"
        exit 1
    fi
    ok "BAP staged (imports renamed)"

    cp "$ANDAIME_REPO/LICENSE" "$STAGE/apps/bap/LICENSE"
    ok "LICENSE copied to apps/bap/"

    # Compile launcher (.exe) with icon if available
    compile_launcher "$STAGE/bap.exe" "$ANDAIME_REPO/launchers/icons/bap.ico"
    ok "bap.exe compiled"
fi

# --- Emissor ---
if [ $BUILD_EMISSOR -eq 1 ]; then
    step "6b" "Staging Emissor..."
    mkdir -p "$STAGE/apps/emissor"
    cp -r "$EMISSOR_REPO/"* "$STAGE/apps/emissor/"

    # Verify no stale src. imports remain
    if grep -r "from src\.\|import src\b" "$STAGE/apps/emissor/" --include="*.py" -q; then
        err "Stale 'src.' imports found in Emissor:"
        grep -rn "from src\.\|import src\b" "$STAGE/apps/emissor/" --include="*.py"
        exit 1
    fi
    ok "Emissor staged (imports renamed)"

    cp "$ANDAIME_REPO/LICENSE" "$STAGE/apps/emissor/LICENSE"
    ok "LICENSE copied to apps/emissor/"

    # Compile launcher (.exe) with icon
    compile_launcher "$STAGE/emissor.exe" "$ANDAIME_REPO/launchers/icons/emissor.ico"
    ok "emissor.exe compiled"
fi

# --- RAC ---
if [ $BUILD_RAC -eq 1 ]; then
    step "6c" "Staging RAC..."
    mkdir -p "$STAGE/apps/rac"
    cp -r "$RAC_REPO/"* "$STAGE/apps/rac/"

    # Verify no stale src. imports remain
    if grep -r "from src\.\|import src\b" "$STAGE/apps/rac/" --include="*.py" -q; then
        err "Stale 'src.' imports found in RAC:"
        grep -rn "from src\.\|import src\b" "$STAGE/apps/rac/" --include="*.py"
        exit 1
    fi
    ok "RAC staged (imports renamed)"

    cp "$ANDAIME_REPO/LICENSE" "$STAGE/apps/rac/LICENSE"
    ok "LICENSE copied to apps/rac/"

    # Compile launcher (.exe) with icon
    compile_launcher "$STAGE/rac.exe" "$ANDAIME_REPO/launchers/icons/rac.ico"
    ok "rac.exe compiled"
fi

# ============================================
# 7. Prune (size optimisation — whitelist approach)
# ============================================
if [ $NO_PRUNE -eq 0 ]; then
    step "7" "Pruning for size..."

    SP="$STAGE/python/Lib/site-packages"
    PYSIDE="$SP/PySide6"

    # --- PySide6: keep ONLY Core/Gui/Widgets (+ ICU + VC runtime) ---
    # The full install ships 133 Qt6 DLLs (297MB), 53 .pyd files, WebEngine
    # (196MB), QML (33MB), resources (102MB), etc. The apps use 3 modules.

    # Remove ALL Qt6*.dll EXCEPT Core, Gui, Widgets.
    find "$PYSIDE" -maxdepth 1 -name "Qt6*.dll" \
        ! -name "Qt6Core.dll" \
        ! -name "Qt6Gui.dll" \
        ! -name "Qt6Widgets.dll" \
        -delete

    # Remove non-Qt DLLs not needed at runtime.
    for f in \
        Qt6WebEngineCore.dll opengl32sw.dll \
        avcodec-61.dll avformat-61.dll avutil-59.dll \
        swscale-8.dll swresample-5.dll \
        pyside6qml.abi3.dll \
        vcamp140.dll vccorlib140.dll concrt140.dll vcomp140.dll; do
        rm -f "$PYSIDE/$f"
    done

    # Remove ALL .pyd EXCEPT Core/Gui/Widgets.
    find "$PYSIDE" -maxdepth 1 -name "*.pyd" \
        ! -name "QtCore.pyd" \
        ! -name "QtGui.pyd" \
        ! -name "QtWidgets.pyd" \
        -delete

    # Remove entire directories not needed at runtime.
    for d in qml resources metatypes include typesystems \
             scripts glue QtAsyncio doc lib support; do
        rm -rf "$PYSIDE/$d"
    done

    # Remove ALL tool executables (development tools, not needed at runtime).
    find "$PYSIDE" -maxdepth 1 -name "*.exe" -delete

    # Remove ALL .pyi type stubs (IDE hints, not loaded at runtime).
    find "$PYSIDE" -maxdepth 1 -name "*.pyi" -delete

    # Remove import libraries and metadata JSON.
    rm -f "$PYSIDE"/*.lib "$PYSIDE"/PySide6_*.json "$PYSIDE/_config.py" \
          "$PYSIDE/_git_pyside_version.py"

    ok "PySide6 stripped to Core/Gui/Widgets (DLLs + PYDs + 2 plugin dirs)"

    # --- Qt plugins: whitelist — keep only platforms/qwindows + imageformats/qjpeg+qpng+qico + iconengines/qsvgicon ---
    QT_PLUGINS="$PYSIDE/plugins"
    if [ -d "$QT_PLUGINS" ]; then
        # Remove ALL plugin subdirs except platforms, imageformats and iconengines.
        find "$QT_PLUGINS" -maxdepth 1 -mindepth 1 -type d \
            ! -name "platforms" \
            ! -name "imageformats" \
            ! -name "iconengines" \
            -exec rm -rf {} +
        # Within those three, keep only the files we need.
        find "$QT_PLUGINS/platforms" -type f ! -name "qwindows.dll" -delete 2>/dev/null || true
        find "$QT_PLUGINS/imageformats" -type f ! -name "qjpeg.dll" ! -name "qpng.dll" ! -name "qico.dll" -delete 2>/dev/null || true
        find "$QT_PLUGINS/iconengines" -type f ! -name "qsvgicon.dll" -delete 2>/dev/null || true
        ok "Qt plugins whitelisted (qwindows + qjpeg + qpng + qico + qsvgicon)"
    fi

    # --- Qt translations: keep only PT ---
    QT_TRANS="$PYSIDE/translations"
    if [ -d "$QT_TRANS" ]; then
        find "$QT_TRANS" -type f ! -name "qtbase_pt*" ! -name "qt_pt*" -delete
        ok "Qt translations pruned"
    fi

    # --- google-api-python-client discovery cache ---
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

    # --- Remove build-tool packages (not needed at runtime) ---
    for pkg in pip setuptools wheel _distutils_hack \
               pyinstaller pyinstaller-hooks-contrib \
               pikepdf pikepdf.libs pikepdf-*.dist-info \
               pythonwin customtkinter darkdetect; do
        rm -rf "$SP/$pkg"
    done
    rm -f "$SP/distutils-precedence.pth"
    ok "Build tools removed (pip, setuptools, pyinstaller, pikepdf, pythonwin, customtkinter)"

    # --- Remove Tcl/Tk (not used by either app) ---
    rm -rf "$STAGE/python/tcl" "$STAGE/python/Lib/tkinter" "$SP/_tkinter"
    rm -f "$STAGE/python/DLLs/tcl86t.dll" "$STAGE/python/DLLs/tk86t.dll"
    ok "Tcl/Tk removed (stdlib + DLLs)"

    # --- Remove Python Doc/Tools/tests/idlelib/ensurepip ---
    rm -rf "$STAGE/python/Doc" "$STAGE/python/Tools"
    find "$STAGE/python/Lib" -type d -name "test" -exec rm -rf {} + 2>/dev/null || true
    rm -rf "$STAGE/python/Lib/idlelib" "$STAGE/python/Lib/ensurepip"
    ok "Stdlib trimmed (docs, tests, idlelib, ensurepip)"

    # --- Remove C headers + import libraries + Scripts (pip etc.) ---
    rm -rf "$STAGE/python/include" "$STAGE/python/libs" "$STAGE/python/Scripts"
    ok "C headers + libs removed"
else
    step "7" "Skipping prune (--no-prune)"
fi

# ============================================
# 8. Clean caches + compile .pyc
# ============================================
step "8" "Compiling .pyc and cleaning caches..."

# Remove stale __pycache__ dirs (clean slate before compiling)
find "$STAGE" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

# Pre-compile only the app source + chassis (site-packages is already compiled by pip).
# Running compileall on the entire Python tree via Wine is extremely slow.
COMPILE_TARGETS=""
[ $BUILD_BAP -eq 1 ]     && COMPILE_TARGETS="$COMPILE_TARGETS $(winepath -w "$STAGE/apps/bap" 2>/dev/null | tr -d '\r')"
[ $BUILD_EMISSOR -eq 1 ] && COMPILE_TARGETS="$COMPILE_TARGETS $(winepath -w "$STAGE/apps/emissor" 2>/dev/null | tr -d '\r')"
[ $BUILD_RAC -eq 1 ]     && COMPILE_TARGETS="$COMPILE_TARGETS $(winepath -w "$STAGE/apps/rac" 2>/dev/null | tr -d '\r')"
COMPILE_TARGETS="$COMPILE_TARGETS $(winepath -w "$STAGE/python/Lib/site-packages/andaime" 2>/dev/null | tr -d '\r')"

if [ -n "$COMPILE_TARGETS" ]; then
    timeout 60 wine "$WINE_PYTHON" -m compileall -q $COMPILE_TARGETS 2>/dev/null | grep -v fixme || true
    ok "App + chassis bytecode compiled"
else
    echo -e "  ${YELLOW}!${NC} No compile targets"
fi

# ============================================
# 9. Report
# ============================================
step "9" "Build complete!"
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
if [ $BUILD_BAP -eq 1 ]; then
    BAP_SIZE=$(du -sh "$STAGE/apps/bap" | cut -f1)
    echo -e "  bap/:    $BAP_SIZE"
fi
if [ $BUILD_EMISSOR -eq 1 ]; then
    EMISSOR_SIZE=$(du -sh "$STAGE/apps/emissor" | cut -f1)
    echo -e "  emissor/: $EMISSOR_SIZE"
fi
if [ $BUILD_RAC -eq 1 ]; then
    RAC_SIZE=$(du -sh "$STAGE/apps/rac" | cut -f1)
    echo -e "  rac/:    $RAC_SIZE"
fi
echo ""
echo "Launchers:"
[ $BUILD_BAP -eq 1 ]     && echo "  $STAGE/bap.exe"
[ $BUILD_EMISSOR -eq 1 ] && echo "  $STAGE/emissor.exe"
[ $BUILD_RAC -eq 1 ]     && echo "  $STAGE/rac.exe"
echo ""

# --- Create dist.zip inside SISTEMAS/ (for network-share deployment) ---
# Must be created AFTER zipping so it doesn't include itself.
ZIP_PATH="$STAGE/dist.zip"
rm -f "$ZIP_PATH"
cd "$DIST"
zip -r "$ZIP_PATH" SISTEMAS/ -q \
    -x "SISTEMAS/dist.zip" \
       "SISTEMAS/bap.exe" \
       "SISTEMAS/emissor.exe" \
       "SISTEMAS/rac.exe" \
       "SISTEMAS/shortcuts.bat"
ZIP_SIZE=$(du -sh "$ZIP_PATH" | cut -f1)
echo -e "  ${GREEN}dist.zip:${NC} $ZIP_SIZE"
echo ""

echo -e "${GREEN}Done.${NC}"
echo "  Network share: copy *.exe + dist.zip + VERSION + shortcuts.bat to the share root"
echo "  Standalone:    copy SISTEMAS/ folder and double-click the .exe"
