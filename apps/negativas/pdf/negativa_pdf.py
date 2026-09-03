"""Gerador de PDF ReportLab para Negativas."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING

from andaime.error_handler import ErrorContext, ErrorHandler, ErrorLevel
from andaime.pdf import PDFConfig, PDFStyleManager, load_svg_drawing, CM

if TYPE_CHECKING:
    from negativas.database.negativas_database import NegativasDatabase
    from negativas.models import NegativaData


from dataclasses import dataclass


@dataclass
class NegativaPDFConfig(PDFConfig):
    """Configurações de PDF específicas para Negativas."""

    margin: float = 1.2 * CM
    LOGO_TARGET_SIZE: float = 1.8 * CM
    LOGO_OFFSET_Y: float = -0.0 * CM


class NegativaPDF:
    """Gera PDF de Negativa a partir de NegativaData."""

    def __init__(self, db: NegativasDatabase) -> None:
        self.db = db
        self.config = NegativaPDFConfig()

    def generate(
        self,
        data: NegativaData,
        output_path: str | Path | None = None,
    ) -> BytesIO | None:
        """Gera o PDF.

        Args:
            data: Dados do formulário.
            output_path: Caminho de saída; se ``None``, retorna ``BytesIO``.

        Returns:
            ``BytesIO`` com o PDF (quando ``output_path`` é ``None``) ou ``None``.
        """
        from reportlab.platypus import SimpleDocTemplate

        elements = self._build_elements(data)

        if output_path:
            target = Path(output_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "wb") as buf:
                doc = self._build_doc(buf)
                doc.build(elements)
            ErrorHandler.log(
                f"PDF gerado: {target}",
                level=ErrorLevel.INFO,
                context=ErrorContext.PDF_GENERATION,
            )
            return None

        buf = BytesIO()
        doc = self._build_doc(buf)
        doc.build(elements)
        buf.seek(0)
        return buf

    # ── internals ────────────────────────────────────────────────────────

    def _build_doc(self, buffer):
        from reportlab.platypus import SimpleDocTemplate

        return SimpleDocTemplate(
            buffer,
            pagesize=self.config.pagesize,
            leftMargin=self.config.margin,
            rightMargin=self.config.margin,
            topMargin=self.config.margin,
            bottomMargin=self.config.margin,
        )

    def _build_elements(self, data: NegativaData) -> list:
        from reportlab.platypus import Paragraph, Spacer, HRFlowable
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER

        styles = PDFStyleManager(self.config)
        div_texto = self._get_divisao_texto(data)
        data_hoje = data.data_hoje or _data_por_extenso()
        nome_daf = data.nome_daf or "____________________"
        nome_dgmi = data.nome_dgmi or "____________________"

        elements: list = []

        # ── Header ───────────────────────────────────────────────────────
        from reportlab.platypus import Table, TableStyle

        logo = load_svg_drawing(
            _brasao_path(),
            self.config.LOGO_TARGET_SIZE,
            offset_y=self.config.LOGO_OFFSET_Y,
        )

        header_style = styles.create_header_style(self.config.FONT_SIZE_LARGE)
        sub_style = styles.create_header_style(self.config.FONT_SIZE_MEDIUM)

        text_content = (
            '<b>MUNICÍPIO DA ESTÂNCIA BALNEÁRIA DE PRAIA GRANDE</b><br/>'
            f'<font size="{self.config.FONT_SIZE_MEDIUM}"><b>Estado de São Paulo</b></font><br/>'
            f'<font size="{self.config.FONT_SIZE_MEDIUM}"><b>SESAP - Secretaria de Saúde Pública</b></font>'
        )
        text_para = Paragraph(text_content, header_style)

        if logo is not None:
            # Centered group: spacer | brasão | spacer | text | spacer
            s1 = self.config.total_width * 0.06
            logo_w = self.config.total_width * 0.14
            s2 = self.config.total_width * 0.04
            text_w = self.config.total_width * 0.70
            s3 = self.config.total_width * 0.06
            table = Table(
                [["", logo, "", text_para, ""]],
                colWidths=[s1, logo_w, s2, text_w, s3],
            )
            table.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]))
            elements.append(table)
        else:
            elements.append(Paragraph(
                "MUNICÍPIO DA ESTÂNCIA BALNEÁRIA DE PRAIA GRANDE",
                header_style,
            ))
            elements.append(Paragraph("Estado de São Paulo", sub_style))
            elements.append(Paragraph("SESAP - Secretaria de Saúde Pública", sub_style))

        elements.append(Spacer(1, 12))

        # ── Divider ──────────────────────────────────────────────────────
        elements.append(HRFlowable(
            width="100%", thickness=1, color=_black(),
            spaceAfter=12, spaceBefore=0,
        ))

        # ── Intro ────────────────────────────────────────────────────────
        normal = styles.create_normal_style()

        left_bold = ParagraphStyle(
            "LeftBold",
            parent=normal,
            fontName="Helvetica-Bold",
            fontSize=self.config.FONT_SIZE_NORMAL,
            alignment=TA_LEFT,
            leading=16,
        )
        left_normal = ParagraphStyle(
            "LeftNormal",
            parent=normal,
            fontSize=self.config.FONT_SIZE_NORMAL,
            alignment=TA_LEFT,
            leading=16,
        )
        right_normal = ParagraphStyle(
            "RightNormal",
            parent=normal,
            fontSize=self.config.FONT_SIZE_NORMAL,
            alignment=TA_RIGHT,
            leading=16,
        )
        center_bold = ParagraphStyle(
            "CenterBold",
            parent=normal,
            fontName="Helvetica-Bold",
            fontSize=self.config.FONT_SIZE_NORMAL,
            alignment=TA_CENTER,
            leading=16,
        )

        elements.append(Paragraph(f"À {data.destinatario},", left_bold))
        elements.append(Spacer(1, 8))
        elements.append(Paragraph(
            f"Ao que cabe à {div_texto}, informo o seguinte acerca dos medicamentos e insumos listados:",
            left_normal,
        ))
        elements.append(Spacer(1, 16))

        # ── Items ────────────────────────────────────────────────────────
        elements.extend(self._build_items(data, left_normal, center_bold))

        # ── Footer ───────────────────────────────────────────────────────
        elements.append(Spacer(1, 40))
        elements.append(Paragraph(f"Praia Grande, {data_hoje}.", right_normal))
        elements.append(Spacer(1, 8))
        elements.append(Paragraph("Atenciosamente,", right_normal))
        elements.append(Spacer(1, 40))

        # Signature blocks
        if data.usos_daf:
            elements.append(Paragraph(f"<b>{nome_daf}</b>", center_bold))
            elements.append(Paragraph(
                "<b>DIVISÃO DE ASSISTÊNCIA FARMACÊUTICA</b>", center_bold,
            ))
            elements.append(Paragraph("SESAP 10.2.02", center_bold))
            elements.append(Spacer(1, 20))

        if data.usos_dgmi:
            elements.append(Paragraph(f"<b>{nome_dgmi}</b>", center_bold))
            elements.append(Paragraph(
                "<b>DIVISÃO DE GESTÃO DE MATERIAIS E INSUMOS</b>", center_bold,
            ))
            elements.append(Paragraph("SESAP 10.6.1.3", center_bold))

        return elements

    def _build_items(self, data: NegativaData, text_style, center_bold) -> list:
        from reportlab.platypus import Paragraph, Spacer

        if not data.itens:
            from reportlab.lib.styles import ParagraphStyle
            from reportlab.lib.enums import TA_LEFT

            italic = ParagraphStyle(
                "Italic",
                parent=text_style,
                fontName="Helvetica-Oblique",
            )
            return [Paragraph("<i>Nenhum item adicionado ainda.</i>", italic)]

        # Cache CEAF medications for CID lookup
        ceaf_names = tuple(item.nome for item in data.itens if item.categoria == "CEAF")
        ceaf_cache: dict = {}
        if ceaf_names:
            for med in self.db.get_medicamentos_por_nomes(list(ceaf_names)):
                ceaf_cache[med.nome] = med

        elements: list = []
        for item in data.itens:
            elements.extend(
                self._build_item(item, ceaf_cache, text_style, center_bold)
            )
            elements.append(Spacer(1, 8))

        return elements

    def _build_item(self, item, ceaf_cache, text_style, center_bold) -> list:
        from reportlab.platypus import Paragraph

        if item.categoria in ("CEAF", "USAFA", "CAPS II"):
            return self._build_medicamento(item, ceaf_cache, text_style, center_bold)
        return self._build_nao_padronizado(item, text_style)

    def _build_medicamento(self, item, ceaf_cache, text_style, center_bold) -> list:
        from reportlab.platypus import Paragraph

        modelo_obj = self.db.get_modelo_por_categoria(item.categoria)
        modelo_texto = modelo_obj.texto if modelo_obj else ""

        parts = [f"<b>{item.nome}</b>: {modelo_texto}"]

        if item.categoria == "CEAF":
            med = ceaf_cache.get(item.nome)
            if med and med.cids:
                prefix = "os CIDs de:" if len(med.cids) > 1 else "o CID de:"
                parts.append(f" contemplando {prefix} {', '.join(med.cids)}.")

        elements = [Paragraph("".join(parts), text_style)]

        if item.em_falta:
            modelo_falta = self.db.get_modelo_por_tipo("falta")
            if modelo_falta:
                elements.append(Paragraph(modelo_falta.texto, text_style))

        return elements

    def _build_nao_padronizado(self, item, text_style) -> list:
        from reportlab.platypus import Paragraph

        tipo_modelo = (
            "nao_padronizado" if item.is_medicamento else "insumo_nao_padronizado"
        )
        modelo_obj = self.db.get_modelo_por_tipo(tipo_modelo)
        if modelo_obj:
            return [Paragraph(f"<b>{item.nome}</b>: {modelo_obj.texto}", text_style)]
        return []

    def _get_divisao_texto(self, data: NegativaData) -> str:
        if data.usos_daf and data.usos_dgmi:
            return "Divisão de Assistência Farmacêutica e Divisão de Gestão de Materiais e Insumos"
        elif data.usos_daf:
            return "Divisão de Assistência Farmacêutica"
        elif data.usos_dgmi:
            return "Divisão de Gestão de Materiais e Insumos"
        return "Divisão de Assistência Farmacêutica e Divisão de Gestão de Materiais e Insumos"


# ── helpers (module-level) ───────────────────────────────────────────────


def _brasao_path() -> Path:
    """Resolve o caminho do SVG do brasão."""
    import sys

    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", str(Path(__file__).parent)))
        return base / "src" / "ui_qt" / "img" / "brasao_prefeitura.svg"
    return Path(__file__).resolve().parent.parent / "ui_qt" / "img" / "brasao_prefeitura.svg"


def _black():
    from reportlab.lib import colors
    return colors.black


def _data_por_extenso() -> str:
    """Data por extenso em português (ex: 23 de agosto de 2026)."""
    from datetime import datetime
    from negativas.constants import MESES_PT

    hoje = datetime.now()
    return f"{hoje.day} de {MESES_PT[hoje.month - 1]} de {hoje.year}"
