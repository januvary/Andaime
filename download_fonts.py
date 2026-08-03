#!/usr/bin/env python3
"""Download fonts for a project based on its FontSpec in main.py."""

import re
import sys
from pathlib import Path

if len(sys.argv) > 1:
    PROJECT_ROOT = Path(sys.argv[1])
else:
    PROJECT_ROOT = Path.cwd()

MAIN_FILE = PROJECT_ROOT / "main.py"

if not MAIN_FILE.exists():
    print(f"Error: main.py not found in {PROJECT_ROOT}")
    sys.exit(1)

# Parse main.py to extract FontSpec
with open(MAIN_FILE, "r", encoding="utf-8") as f:
    content = f.read()

font_family = None
font_size = 11
style_hint = None
bundled = True
fontsource_id = None

# Try to find FontSpec(...) calls - use DOTALL for multiline
matches = list(re.finditer(r"FontSpec\([^)]*\)", content, re.DOTALL))

if not matches:
    print("No FontSpec found in main.py")
    sys.exit(1)

spec_str = matches[0].group(0)

# Parse keyword args: family="IBM Plex Sans"
family_match = re.search(r'family\s*=\s*["\']([^"\']+)["\']', spec_str)
if family_match:
    font_family = family_match.group(1)

# Try positional args first: FontSpec("Roboto", 11, ...)
if not font_family:
    pos_match = re.search(r'FontSpec\(\s*["\']([^"\']+)["\']', spec_str)
    if pos_match:
        font_family = pos_match.group(1)

# Parse size
size_match = re.search(r'size\s*=\s*(\d+)', spec_str)
if size_match:
    font_size = int(size_match.group(1))

# Parse bundled
bundled_match = re.search(r"bundled\s*=\s*(True|False)", spec_str)
if bundled_match:
    bundled = bundled_match.group(1) == "True"

# Parse style_hint
style_hint_match = re.search(r"style_hint\s*=\s*QFont\.StyleHint\.(\w+)", spec_str)
if style_hint_match:
    style_hint = style_hint_match.group(1)

# Parse fontsource_id
fontsource_id_match = re.search(r'fontsource_id\s*=\s*["\']([^"\']+)["\']', spec_str)
if fontsource_id_match:
    fontsource_id = fontsource_id_match.group(1)

if not font_family:
    print("No FontSpec found in main.py")
    sys.exit(1)

print(f"Font: {font_family}")
print(f"Size: {font_size}")
print(f"StyleHint: {style_hint or 'SansSerif'}")
print(f"Bundled: {bundled}")
print(f"Fontsource ID: {fontsource_id or 'auto'}")

# Download the font
sys.path.insert(0, "/home/jvanery/Projects/Andaime")
from andaime.qt.fonts import download_font

fonts_dir = PROJECT_ROOT / "fonts"
fonts_dir.mkdir(exist_ok=True)

family_id = fontsource_id or font_family.lower().replace(" ", "-")

print(f"Downloading {font_family} to {fonts_dir}...")

download_font(
    family_id,
    fonts_dir,
    subsets=["latin"],
    weights=["400", "700"],
    styles=["normal", "italic"],
)

print(f"Done! Font files installed in {fonts_dir}")