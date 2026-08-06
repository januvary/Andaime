"""Modelo de tema baseado em rampa + níveis (andaime).

Este módulo é a fonte lógica do tema independente da UI: deriva paletas a
partir da rampa (_RAMP), dos níveis (_LEVELS) e do mapeamento papel→nível
(_ROLE_LEVEL), e serializa/grava o bloco de tema em ``andaime.qt.theme``.

Não depende de widgets — só de ``andaime.qt.theme`` (dados) e de helpers de cor.

Ver também ``tools/theme_studio.py`` (editor) e ``tools/generate_brasao.py``.
"""

from __future__ import annotations

from pathlib import Path

from andaime.qt.theme import (
    LEVEL_COMMENTS,
    SEMANTIC_KEYS,
    SURFACE_KEYS,
)

# ---- Helpers de cor ----


def clamp(v: int) -> int:
    """Limita um canal ao intervalo 0-255."""
    return max(0, min(255, v))


def shift(hex_color: str, channel: int, delta: int) -> str:
    """Aplica delta a um canal (0=R,1=G,2=B) de um hex #rrggbb."""
    h = hex_color.lstrip("#")
    rgb = [int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)]
    rgb[channel] = clamp(rgb[channel] + delta)
    return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"


def to_rgb(hex_color: str) -> list[int]:
    """Hex #rrggbb -> [r, g, b] inteiros 0-255."""
    h = hex_color.lstrip("#")
    return [int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)]


def to_hex(rgb: list[float]) -> str:
    """[r, g, b] (floats) -> hex #rrggbb, com clamp e arredondamento."""
    r, g, b = (clamp(round(c)) for c in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def lerp(lo: str, hi: str, t: float) -> str:
    """Interpola linearmente entre dois hex #rrggbb na posição t."""
    a, b = to_rgb(lo), to_rgb(hi)
    return to_hex([a[i] + (b[i] - a[i]) * t for i in range(3)])


def luminance(hex_color: str) -> float:
    """Luminância relativa WCAG de um hex #rrggbb (0=preto, 1=branco)."""

    def chan(v: int) -> float:
        c = v / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = to_rgb(hex_color)
    return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b)


def contrast(a: str, b: str) -> float:
    """Razão de contraste WCAG entre dois hex #rrggbb."""
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


# ---- Modelo de rampa ----


def derive_palette(
    ramp: dict[str, list[str]],
    levels: dict[int, float],
    roles: dict[str, dict[str, int]],
    sem: dict[str, dict[str, str]],
    mode: str,
) -> dict[str, str]:
    """Deriva a paleta de um modo a partir da rampa + níveis + papéis.

    cor(papel) = lerp(lo, hi, t)  com DARK usando (1 - t) (negativo da rampa).
    ``roles`` é por modo: ``roles[mode][papel] -> nível``.
    As cores semânticas são sobrepostas por cima das superfícies.
    """
    lo, hi = ramp[mode]
    flip = mode == "DARK"
    pal: dict[str, str] = {}
    for role, lvl in roles[mode].items():
        t = levels[lvl]
        pal[role] = lerp(lo, hi, (1 - t) if flip else t)
    pal.update(sem[mode])
    return pal


def theme_block(
    ramp: dict[str, list[str]],
    levels: dict[int, float],
    roles: dict[str, int],
    sem: dict[str, dict[str, str]],
) -> list[str]:
    """Gera as linhas de _RAMP.._SEMANTIC (formato black), inclusive."""
    out: list[str] = []
    out.append("_RAMP: dict[str, tuple[str, str]] = {")
    for m in ("LIGHT", "DARK"):
        lo, hi = ramp[m]
        out.append(f'    "{m}": ("{lo}", "{hi}"),')
    out.append("}")
    out.append("")
    out.append("# Nível -> posição t na rampa (do mais escuro ao mais claro).")
    out.append("_LEVELS: dict[int, float] = {")
    for lvl in sorted(levels):
        comment = LEVEL_COMMENTS.get(lvl)
        tail = f"  # {comment}" if comment else ""
        out.append(f"    {lvl}: {round(levels[lvl], 4)},{tail}")
    out.append("}")
    out.append("")
    out.append("# Papel (role) -> nível, por modo (Light/Dark).")
    out.append("_ROLE_LEVEL: dict[str, dict[str, int]] = {")
    for m in ("LIGHT", "DARK"):
        out.append(f'    "{m}": {{')
        for lvl in sorted(levels):
            in_level = [r for r in SURFACE_KEYS if roles[m].get(r) == lvl]
            for role in in_level:
                out.append(f'        "{role}": {lvl},')
        out.append("    },")
    out.append("}")
    out.append("")
    out.append("_SEMANTIC: dict[str, dict[str, str]] = {")
    for m in ("LIGHT", "DARK"):
        out.append(f'    "{m}": {{')
        for k in SEMANTIC_KEYS:
            out.append(f'        "{k}": "{sem[m][k]}",')
        out.append("    },")
    out.append("}")
    return out


def write_theme(
    theme_file: Path,
    ramp: dict[str, list[str]],
    levels: dict[int, float],
    roles: dict[str, int],
    sem: dict[str, dict[str, str]],
) -> None:
    """Reescreve o bloco _RAMP.._SEMANTIC em andaime.qt.theme (preserva o resto)."""
    lines = Path(theme_file).read_text(encoding="utf-8").split("\n")
    start = next(i for i, ln in enumerate(lines) if ln.startswith("_RAMP:"))
    sem_start = next(i for i, ln in enumerate(lines) if ln.startswith("_SEMANTIC:"))
    end = next(i for i in range(sem_start, len(lines)) if lines[i] == "}")
    block = theme_block(ramp, levels, roles, sem)
    new = lines[:start] + block + lines[end + 1 :]
    Path(theme_file).write_text("\n".join(new), encoding="utf-8")
