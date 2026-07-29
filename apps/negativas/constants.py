"""Constantes do Sistema de Negativas"""

from pathlib import Path

# ── Identificação do App ────────────────────────────────────────
APP_NAME = "Negativas"
APP_DISPLAY_NAME = "Sistema de Negativas - SESAP PG"
UPDATE_REPO = ""  # Preencher com user/repo para atualizações automáticas

# ── Caminhos ─────────────────────────────────────────────────────
# Resolvido em runtime para funcionar tanto em dev quanto em build
_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Caminhos relativos ao projeto
DATA_DIR = _PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "database.db"
CONFIG_PATH = DATA_DIR / "config.json"
BRASAO_SVG_PATH = Path(__file__).resolve().parent / "ui_qt" / "img" / "brasao_prefeitura.svg"

# ── Interface ───────────────────────────────────────────────────
DEBOUNCE_MS = 150  # Delay para preview atualizar ao digitar
BRASAO_HEIGHT = 60  # Altura do brasão em px (app preview + HTML)

# ─── Dados ───────────────────────────────────────────────────────
MESES_PT = [
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
]