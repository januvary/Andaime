#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gerenciamento de Estilos e Flowables para PDF ReportLab

Centraliza criação de estilos Paragraph e wrappers Flowable,
eliminando estado global e melhorando testabilidade.
"""

from typing import cast

from reportlab.lib.enums import TA_CENTER
from reportlab.lib.styles import ParagraphStyle
from andaime.pdf import PDFStyleManager as BasePDFStyleManager


# Re-export for backward compatibility
DrawingFlowable = None  # Removed — use andaime.pdf.load_svg_drawing instead


class PDFStyleManager(BasePDFStyleManager):
    """Gerenciador de estilos Emissor — estilos base + métodos auxiliares."""

    def get_style(self, name: str) -> ParagraphStyle:
        """Retorna estilo pelo nome."""
        return cast(ParagraphStyle, self._styles[name])

    def create_table_header_style(self) -> ParagraphStyle:
        """Retorna estilo para cabeçalhos de tabela."""
        return self.get_style("BoldSmall")

    def create_small_style(self) -> ParagraphStyle:
        """Retorna estilo para texto pequeno."""
        return self.get_style("Small")

    def create_bold_small_style(self) -> ParagraphStyle:
        """Retorna estilo para texto pequeno em negrito."""
        return self.get_style("BoldSmall")

    def create_bold_centered_style(self) -> ParagraphStyle:
        """Retorna estilo para texto centralizado em negrito."""
        return self.get_style("BoldCenter")

    def create_proxima_retirada_style(self) -> ParagraphStyle:
        """Retorna estilo para a linha de próxima retirada no recibo."""
        return ParagraphStyle(
            name="ProximaRetirada",
            parent=self._styles["Normal"],
            fontSize=14,
            alignment=TA_CENTER,
            fontName="Helvetica-Bold",
            leading=19,
        )

    def create_header_medium_style(self) -> ParagraphStyle:
        """Retorna estilo para cabeçalho médio."""
        return self.get_style("HeaderMedium")

    def create_normal_style(self) -> ParagraphStyle:
        """Retorna estilo normal."""
        return cast(ParagraphStyle, self._styles["Normal"])
