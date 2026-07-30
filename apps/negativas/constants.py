"""Constantes do Sistema de Negativas"""

from pathlib import Path

# ── Identificação do App ────────────────────────────────────────
APP_NAME = "Negativas"
APP_DISPLAY_NAME = "Sistema de Negativas - SESAP PG"
UPDATE_REPO = "januvary/negativas"

# ── Caminhos ─────────────────────────────────────────────────────
# Resolvido em runtime para funcionar tanto em dev quanto em build
# Agora usando o sistema de caminhos padrão do Andaime para
# suporte a shares de rede e instalações locais

BRASAO_SVG_PATH = Path(__file__).resolve().parent / "ui_qt" / "img" / "brasao_prefeitura.svg"

# ── Interface ───────────────────────────────────────────────────
DEBOUNCE_MS = 150  # Delay para preview atualizar ao digitar
BRASAO_HEIGHT = 60  # Altura do brasão em px (app preview + HTML)

# ─── Dados ───────────────────────────────────────────────────────
MESES_PT = [
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
]