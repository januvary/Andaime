#!/bin/bash
# ============================================
# SISTEMAS — Build Library
# Shared functions for standalone and portable builds
# ============================================

set -euo pipefail

# --- Paths ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ANDAIME_REPO="$SCRIPT_DIR"
WINE_PY_DIR="$HOME/.wine/drive_c/Python310"
WINE_PYTHON="C:\\Python310\\python.exe"

# --- App Registry (unified format: module|repo|src_path|icon_path|display_name|app_folder) ---
declare -A APPS
APPS[bap]="bap|januvary/bap|$HOME/Projects/SS 54 - Vindication|$ANDAIME_REPO/launchers/icons/bap.ico|BAP|BAP"
APPS[emissor]="emissor|januvary/Emissor|$HOME/Projects/Emissor|$ANDAIME_REPO/launchers/icons/emissor.ico|Emissor|Emissor"
APPS[rac]="rac|januvary/RAC|$HOME/Projects/RAC - Registros Alto Custo|$ANDAIME_REPO/launchers/icons/rac.ico|RAC|RAC"
APPS[negativas]="negativas|januvary/negativas|$HOME/Projects/SISTEMA DE NEGATIVAS|$ANDAIME_REPO/launchers/icons/negativas.ico|Negativas|Negativas"

# --- Helpers ---
app_field() { echo "$1" | cut -d'|' -f"$2"; }
app_name() { echo "$1" | cut -d'|' -f1; }
app_src() { echo "$1" | cut -d'|' -f3; }
app_icon() { echo "$1" | cut -d'|' -f4; }
app_repo() { echo "$ANDAIME_REPO/apps/$(app_name "$1")"; }

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'
step() { echo -e "\n${YELLOW}[$1]${NC} $2"; }
ok()   { echo -e "  ${GREEN}✓${NC} $1"; }
err()  { echo -e "  ${RED}✗${NC} $1"; }

# --- Clean bytecode cache ---
clean_bytecode() {
    local dir="$1"
    find "$dir" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    find "$dir" -type f -name "*.pyc" -delete 2>/dev/null || true
}

# --- Sync app source ---
sync_app() {
    local app="$1"
    local app_info="${APPS[$app]}"
    local module=$(app_field "$app_info" 1)
    local src=$(app_field "$app_info" 3)
    local icon=$(app_field "$app_info" 4)

    local dst="$ANDAIME_REPO/apps/$app"
    rm -rf "$dst"
    mkdir -p "$dst"

    # Copy src/ contents
    if [ -d "$src/src" ]; then
        cp -r "$src/src/"* "$dst/"
    fi

    # Copy main.py → __main__.py
    if [ -f "$src/main.py" ]; then
        cp "$src/main.py" "$dst/__main__.py"
    fi

    # Copy icon
    if [ -f "$icon" ]; then
        cp "$icon" "$dst/icon.ico"
    fi

    clean_bytecode "$dst"

    # Rename imports src. → <module>.
    find "$dst" -name "*.py" -print0 | xargs -0 sed -i \
        -e "s/from src\\./from ${module}./g" \
        -e "s/from src import/from ${module} import/g" \
        -e "s/import src\\b/import ${module}/g"

    # Remove legacy sys.path bootstrap
    sed -i '/sys\.path\.insert(0, os\.path\.dirname/d' "$dst/__main__.py" 2>/dev/null || true

    # BAP-specific: add pathlib import
    if [[ "$app" == "bap" ]]; then
        sed -i '1a from pathlib import Path' "$dst/__main__.py"
    fi

    # Verify no stale imports
    if grep -r "from src\.\|import src\b" "$dst/" --include="*.py" -q; then
        err "Stale 'src.' imports found in $app:"
        grep -rn "from src\.\|import src\b" "$dst/" --include="*.py"
        return 1
    fi

    ok "$app synced to apps/$app/"
}

# --- Check prerequisites ---
check_prerequisites() {
    local mode="$1"
    local apps_to_check="$2"

    step "1" "Checking prerequisites..."

    if ! command -v wine &>/dev/null; then
        err "Wine is not installed"
        return 1
    fi

    if ! command -v x86_64-w64-mingw32-gcc &>/dev/null; then
        err "mingw64-gcc is not installed (needed to compile launcher)"
        return 1
    fi

    if [ ! -d "$WINE_PY_DIR" ]; then
        err "Wine Python not found: $WINE_PY_DIR"
        return 1
    fi

    if [ ! -d "$ANDAIME_REPO" ]; then
        err "Andaime repo not found: $ANDAIME_REPO"
        return 1
    fi

    ok "Wine: $(wine --version 2>&1 | head -1)"
    ok "mingw: $(x86_64-w64-mingw32-gcc -dumpmachine)"
    ok "Wine Py: $WINE_PY_DIR"
    ok "Andaime: $ANDAIME_REPO"

    # Check app sources
    for app in $apps_to_check; do
        if [ -n "${APPS[$app]+x}" ]; then
            app_info="${APPS[$app]}"
            src=$(app_field "$app_info" 3)
            display=$(app_field "$app_info" 5)
            if [ ! -d "$src" ]; then
                err "$display source not found: $src"
                return 1
            fi
            ok "$display: $src"
        fi
    done

    return 0
}

# --- Compute runtime hash ---
compute_runtime_hash() {
    wine "$WINE_PYTHON" -m pip freeze 2>/dev/null | sort | sha256sum | cut -c1-8
}

# --- Prepare Wine Python dependencies ---
prepare_wine_python() {
    local skip_deps="$1"

    if [[ "$skip_deps" -eq 1 ]]; then
        step "2" "Skipping dependency installation (--skip-deps)"
        return 0
    fi

    step "2" "Preparing Wine Python dependencies..."

    wine "$WINE_PYTHON" -m pip install --upgrade \
        pyside6_essentials==6.7.3 pypdfium2 pypdf holidays typing_extensions \
        openpyxl pywin32 \
        google-api-python-client google-auth-oauthlib google-auth rapidfuzz \
        reportlab svglib python-dotenv requests \
        > /dev/null 2>&1 && \
    wine "$WINE_PYTHON" -m pip install --no-deps img2pdf \
        > /dev/null 2>&1

    ok "Wine Python deps ready"
}

# --- Copy Windows Python tree ---
copy_python() {
    local stage="$1"

    step "3" "Copying Windows Python tree..."
    cp -r "$WINE_PY_DIR/"* "$stage/python/"

    # Remove stale andaime editable install
    rm -f "$stage/python/Lib/site-packages/__editable__.andaime-*.pth"
    rm -f "$stage/python/Lib/site-packages/__editable___andaime*.py"
    rm -rf "$stage/python/Lib/site-packages/andaime.egg-link"
    rm -rf "$stage/python/Lib/site-packages/andaime-*.dist-info"

    local size=$(du -sh "$stage/python" | cut -f1)
    ok "Python copied ($size)"

    # sitecustomize.py (disable bytecode on network shares)
    cp "$ANDAIME_REPO/launchers/sitecustomize.py" "$stage/python/Lib/site-packages/sitecustomize.py"
    ok "sitecustomize.py copied (disables .pyc on network shares)"

    # Third-party license pointer
    cp "$ANDAIME_REPO/THIRD_PARTY_LICENSES" "$stage/python/THIRD_PARTY_LICENSES"
    ok "THIRD_PARTY_LICENSES copied to python/"
}

# --- Copy andaime chassis ---
copy_andaime() {
    local stage="$1"

    step "4" "Copying andaime chassis..."
    cp -r "$ANDAIME_REPO/andaime" "$stage/python/Lib/site-packages/andaime"
    cp "$ANDAIME_REPO/LICENSE" "$stage/python/Lib/site-packages/andaime/LICENSE"
    ok "Chassis → site-packages/andaime/ (+ LICENSE)"
}

# --- Stage app code ---
stage_app() {
    local app="$1" stage="$2"

    local app_repo_dir="$ANDAIME_REPO/apps/$app"
    local stage_app_dir="$stage/apps/$app"

    mkdir -p "$stage_app_dir"
    cp -r "$app_repo_dir/"* "$stage_app_dir/"
    cp "$ANDAIME_REPO/LICENSE" "$stage_app_dir/LICENSE"

    ok "$app staged (imports renamed)"

    # Regenerate PNG icons from SVGs so runtime never depends on Qt SVG plugins.
    if [ -f "$stage_app_dir/tools/generate_tile_icons.py" ]; then
        (cd "$stage_app_dir" && PYTHONPATH="$stage_app_dir" python -m tools.generate_tile_icons)
        ok "$app tile icons regenerated as PNG"
    fi
}

# --- Prune Python (unified conservative approach) ---
prune_python() {
    local stage="$1" no_prune="$2"

    if [[ "$no_prune" -eq 1 ]]; then
        step "5" "Skipping prune (--no-prune)"
        return 0
    fi

    step "5" "Pruning for size..."

    local sp="$stage/python/Lib/site-packages"
    local pyside="$sp/PySide6"

    # --- PySide6: keep ONLY Core/Gui/Widgets ---
    find "$pyside" -maxdepth 1 -name "Qt6*.dll" \
        ! -name "Qt6Core.dll" \
        ! -name "Qt6Gui.dll" \
        ! -name "Qt6Widgets.dll" \
        -delete

    for f in \
        Qt6WebEngineCore.dll opengl32sw.dll \
        avcodec-61.dll avformat-61.dll avutil-59.dll \
        swscale-8.dll swresample-5.dll \
        pyside6qml.abi3.dll \
        vcamp140.dll vccorlib140.dll concrt140.dll vcomp140.dll \
        vcruntime140.dll vcruntime140_1.dll; do
        rm -f "$pyside/$f"
    done

    find "$pyside" -maxdepth 1 -name "*.pyd" \
        ! -name "QtCore.pyd" \
        ! -name "QtGui.pyd" \
        ! -name "QtWidgets.pyd" \
        -delete

    for d in qml resources metatypes include typesystems \
             scripts glue QtAsyncio doc lib support; do
        rm -rf "$pyside/$d"
    done

    find "$pyside" -maxdepth 1 -name "*.exe" -delete
    find "$pyside" -maxdepth 1 -name "*.pyi" -delete
    rm -f "$pyside"/*.lib "$pyside"/PySide6_*.json "$pyside/_config.py" \
          "$pyside/_git_pyside_version.py"

    ok "PySide6 stripped to Core/Gui/Widgets"

    # --- Qt plugins: whitelist ---
    local qt_plugins="$pyside/plugins"
    if [ -d "$qt_plugins" ]; then
        find "$qt_plugins" -maxdepth 1 -mindepth 1 -type d \
            ! -name "platforms" \
            ! -name "imageformats" \
            ! -name "iconengines" \
            -exec rm -rf {} +
        find "$qt_plugins/platforms" -type f ! -name "qwindows.dll" -delete 2>/dev/null || true
        find "$qt_plugins/imageformats" -type f ! -name "qjpeg.dll" ! -name "qpng.dll" ! -name "qico.dll" -delete 2>/dev/null || true
        find "$qt_plugins/iconengines" -type f ! -name "qsvgicon.dll" -delete 2>/dev/null || true
        ok "Qt plugins whitelisted"
    fi

    # --- Qt translations: keep only PT ---
    local qt_trans="$pyside/translations"
    if [ -d "$qt_trans" ]; then
        find "$qt_trans" -type f ! -name "qtbase_pt*" ! -name "qt_pt*" -delete
        ok "Qt translations pruned"
    fi

    # --- Google discovery cache ---
    local gcache="$sp/googleapiclient/discovery_cache/documents"
    if [ -d "$gcache" ]; then
        find "$gcache" -maxdepth 1 -type f ! -name "gmail.v1.json" ! -name "drive.v3.json" -delete
        ok "Google discovery cache trimmed"
    fi

    # --- holidays: keep only Brazil ---
    local hol="$sp/holidays"
    if [ -d "$hol/countries" ]; then
        find "$hol/countries" -maxdepth 1 -type f -name "*.py" \
            ! -name "__init__.py" ! -name "brazil.py" -delete
        cat > "$hol/countries/__init__.py" <<'PYEOF'
from holidays.countries.brazil import Brazil, BR, BRA
PYEOF
        rm -rf "$hol/financial"
        sed -i '/from holidays.financial import \*/d' "$hol/__init__.py" 2>/dev/null || true
        sed -i '/EntityLoader.load("financial", globals())/d' "$hol/__init__.py" 2>/dev/null || true
        ok "holidays trimmed to Brazil"
    fi

    # --- Remove build-tool packages ---
    for pkg in pip setuptools wheel _distutils_hack \
               pyinstaller PyInstaller pyinstaller-hooks-contrib _pyinstaller_hooks_contrib \
               pikepdf pikepdf.libs pikepdf-*.dist-info \
               pythonwin customtkinter darkdetect PyWin32.chm; do
        rm -rf "$sp/$pkg"
    done
    rm -f "$sp/distutils-precedence.pth"
    ok "Build tools removed (pip, setuptools, pyinstaller, pikepdf, pythonwin, customtkinter)"

    # --- Remove Tcl/Tk ---
    rm -rf "$stage/python/tcl" "$stage/python/Lib/tkinter" "$sp/_tkinter"
    rm -f "$stage/python/DLLs/tcl86t.dll" "$stage/python/DLLs/tk86t.dll"
    ok "Tcl/Tk removed (stdlib + DLLs)"

    # --- Remove shiboken6 runtime DLLs ---
    local shiboken="$sp/shiboken6"
    if [ -d "$shiboken" ]; then
        for f in vcruntime140.dll vcruntime140_1.dll msvcp140.dll msvcp140_1.dll msvcp140_2.dll msvcp140_codecvt_ids.dll concrt140.dll; do
            rm -f "$shiboken/$f"
        done
        ok "Shiboken6 runtime DLLs removed (use python/ root versions)"
    fi

    # --- Stdlib trim (conservative) ---
    rm -rf "$stage/python/Doc" "$stage/python/Tools"
    find "$stage/python/Lib" -type d -name "test" -exec rm -rf {} + 2>/dev/null || true
    rm -rf "$stage/python/Lib/idlelib" "$stage/python/Lib/ensurepip"
    rm -rf "$stage/python/Lib/turtledemo" "$stage/python/Lib/pydoc_data"
    rm -rf "$stage/python/Lib/venv" "$stage/python/Lib/msilib"
    rm -rf "$stage/python/Lib/include" "$stage/python/Lib/libs" "$stage/python/Scripts"

    # Remove standalone python.exe (not needed for -m launches)
    rm -f "$stage/python/python.exe"
    rm -f "$stage/python/NEWS.txt"

    # python3.dll is required by PySide6/Shiboken6 .pyd extensions - keep it

    # Keep urllib, http, email, logging, concurrent, asyncio, xml, xmlrpc,
    # multiprocessing, distutils (needed by runtime imports)

    ok "Stdlib trimmed conservatively"
}

# --- Compile bytecode ---
compile_bytecode() {
    local stage="$1" apps="$2"

    step "6" "Compiling bytecode..."
    find "$stage" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

    local compile_targets=""
    for app in $apps; do
        compile_targets="$compile_targets $(winepath -w "$stage/apps/$app" 2>/dev/null | tr -d '\r')"
    done
    compile_targets="$compile_targets $(winepath -w "$stage/python/Lib/site-packages/andaime" 2>/dev/null | tr -d '\r')"

    if [ -n "$compile_targets" ]; then
        timeout 60 wine "$WINE_PYTHON" -m compileall -q $compile_targets 2>/dev/null | grep -v fixme || true
        ok "App + chassis bytecode compiled"
    else
        echo -e "  ${YELLOW}!${NC} No compile targets"
    fi
}

# --- Compile launcher ---
compile_launcher() {
    local output="$1"
    local icon="$2"
    local mode="$3"  # "standalone" or "portable"
    local app_info="$4"

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
    } > "$rc_dir/app.rc"

    x86_64-w64-mingw32-windres "$rc_dir/app.rc" "$rc_dir/app_res.o" 2>/dev/null

    local gcc_cmd="x86_64-w64-mingw32-gcc -O2 -s -o \"$output\" \"$ANDAIME_REPO/launcher.c\" \"$ANDAIME_REPO/miniz.c\" \"$ANDAIME_REPO/miniz_zip.c\" \"$ANDAIME_REPO/miniz_tdef.c\" \"$ANDAIME_REPO/miniz_tinfl.c\" \"$rc_dir/app_res.o\" -mwindows -static -lcomctl32"

    if [[ "$mode" == "standalone" ]]; then
        local repo=$(app_field "$app_info" 2)
        local module=$(app_field "$app_info" 1)
        local display=$(app_field "$app_info" 5)
        gcc_cmd="$gcc_cmd -lwininet -DAPP_REPO=\\\"$repo\\\" -DAPP_MODULE=\\\"$module\\\" -DAPP_DISPLAY=\\\"$display\\\""
    elif [[ "$mode" == "portable" ]]; then
        # Portable mode: use shared SISTEMAS install, extract from local dist.zip only
        # Do NOT add APP_REPO/APP_MODULE/APP_DISPLAY or lwininet
        # PORTABLE_MODE flag enables dist.zip fallback path in launcher
        gcc_cmd="$gcc_cmd -DPORTABLE_MODE=1"
    fi

    eval "$gcc_cmd"

    rm -rf "$rc_dir"

    if [[ "$mode" == "standalone" ]]; then
        local repo=$(app_field "$app_info" 2)
        ok "launcher.exe compiled ($repo)"
    else
        ok "launcher.exe compiled (portable with GitHub + local fallback)"
    fi
}