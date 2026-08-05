#!/bin/bash
# Download fonts for a project based on its FontSpec in main.py

set -euo pipefail

PROJECT_ROOT="${1:-.}"

if [ ! -f "$PROJECT_ROOT/main.py" ]; then
    echo "Error: main.py not found in $PROJECT_ROOT"
    exit 1
fi

python3 -c "
import sys
import re
from pathlib import Path

PROJECT_ROOT = Path('$PROJECT_ROOT')
MAIN_FILE = PROJECT_ROOT / 'main.py'

# Parse main.py to extract FontSpec
with open(MAIN_FILE, 'r', encoding='utf-8') as f:
    content = f.read()

font_family = None
font_size = 11
style_hint = None
bundled = True
fontsource_id = None

# Try to find FontSpec(...) calls
matches = re.finditer(r'FontSpec\([^)]*\)', content)
for match in matches:
    spec_str = match.group(0)

    # Parse positional args: FontSpec(\"Roboto\", 11, ...)
    args_match = re.search(r'FontSpec\(\s*[\"']([^\"']+)[\"']\s*,\s*(\d+)', spec_str)
    if args_match:
        font_family = args_match.group(1)
        font_size = int(args_match.group(2))

    # Parse keyword args
    bundled_match = re.search(r'bundled\s*=\s*(True|False)', spec_str)
    if bundled_match:
        bundled = bundled_match.group(1) == 'True'

    style_hint_match = re.search(r'style_hint\s*=\s*QFont\.StyleHint\.(\w+)', spec_str)
    if style_hint_match:
        style_hint = style_hint_match.group(1)

    fontsource_id_match = re.search(r'fontsource_id\s*=\s*[\"']([^\"']+)[\"']', spec_str)
    if fontsource_id_match:
        fontsource_id = fontsource_id_match.group(1)

    break

if not font_family:
    print('No FontSpec found in main.py')
    sys.exit(1)

print(f'Font: {font_family}')
print(f'Size: {font_size}')
print(f'StyleHint: {style_hint or \"SansSerif\"}')
print(f'Bundled: {bundled}')
print(f'Fontsource ID: {fontsource_id or \"auto\"}')

# Download the font
sys.path.insert(0, '/home/jvanery/Projects/Andaime')
from andaime.qt.fonts import download_font

fonts_dir = PROJECT_ROOT / 'fonts'
fonts_dir.mkdir(exist_ok=True)

family_id = fontsource_id or font_family.lower().replace(' ', '-')

print(f'Downloading {font_family} to {fonts_dir}...')

download_font(
    family_id,
    fonts_dir,
    subsets=['latin'],
    weights=['400', '700'],
    styles=['normal', 'italic'],
)

print(f'Done! Font files installed in {fonts_dir}')
"