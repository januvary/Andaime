#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gerenciamento de Estilos e Flowables para PDF ReportLab

Centraliza criação de estilos Paragraph e wrappers Flowable,
eliminando estado global e melhorando testabilidade.
"""

from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import Flowable
from typing import Any, cast
from emissor.pdf.pdf_config import PDFConfig

# ============================================================================
# FLOWABLE WRAPPER PARA SVG DRAWING
# ============================================================================


class _DrawingFlowable(Flowable):
    """
    Flowable wrapper para reportlab.graphics.Drawing em tabelas.

    Permite que Drawing objects do svglib sejam usados em células de tabela
    do ReportLab Platypus, implementando a interface Flowable corretamente.

    Suporta ajuste fino de posicionamento vertical via offset_y.

    Nota: GraphicsFlowable foi removido no ReportLab 4.4.7, então este
    wrapper customizado é necessário.
    """

    def __init__(self, drawing: Any, offset_y: float = 0) -> None:
        """
        Inicializa wrapper com Drawing.

        Args:
            drawing: reportlab.graphics.Drawing object (do svglib)
            offset_y: Deslocamento vertical (positivo = move para baixo)
        """
        super().__init__()
        self.drawing = drawing
        self.offset_y = offset_y
        self.width = drawing.width
        self.height = drawing.height

    def wrap(self, _aW: float, _aH: float) -> tuple[float, float]:
        """Retorna dimensões do Flowable (interface Flowable)."""
        return (self.width, self.height)

    def draw(self) -> None:
        """Desenha o SVG no canvas com ajuste vertical (interface Flowable)."""
        self.canv.saveState()
        # Mover para baixo por offset_y (valores positivos = para baixo)
        self.canv.translate(0, -self.offset_y)
        self.drawing.drawOn(self.canv, 0, 0)
        self.canv.restoreState()


# ============================================================================
# GERENCIADOR DE ESTILOS
# ============================================================================


class PDFStyleManager:
    """
    Gerenciador centralizado de estilos ReportLab.

    Cria e gerencia todos os ParagraphStyles usados na geração de PDF,
    eliminando o cache global e permitindo múltiplas instâncias com
    configurações diferentes.
    """

    def __init__(self, config: PDFConfig):
        """
        Inicializa gerenciador de estilos.

        Args:
            config: Configurações PDF (para acessar tamanhos de fonte)
        """
        self.config = config
        self._styles = getSampleStyleSheet()
        self._setup_custom_styles()

    def _setup_custom_styles(self) -> None:
        """Cria estilos customizados além dos padrões ReportLab."""
        # Bold centered style
        self._styles.add(
            ParagraphStyle(
                name="BoldCenter",
                parent=self._styles["Normal"],
                fontSize=self.config.FONT_SIZE_NORMAL,
                alignment=TA_CENTER,
                fontName="Helvetica-Bold",
                leading=14,
            )
        )

        # Header large
        self._styles.add(
            ParagraphStyle(
                name="HeaderLarge",
                parent=self._styles["Normal"],
                fontSize=self.config.FONT_SIZE_LARGE,
                alignment=TA_CENTER,
                fontName="Helvetica-Bold",
                leading=16,
            )
        )

        # Header medium
        self._styles.add(
            ParagraphStyle(
                name="HeaderMedium",
                parent=self._styles["Normal"],
                fontSize=self.config.FONT_SIZE_MEDIUM,
                alignment=TA_CENTER,
                fontName="Helvetica-Bold",
                leading=14,
            )
        )

        # Small text
        self._styles.add(
            ParagraphStyle(
                name="Small",
                parent=self._styles["Normal"],
                fontSize=self.config.FONT_SIZE_SMALL,
                leading=11,
            )
        )

        # Bold small
        self._styles.add(
            ParagraphStyle(
                name="BoldSmall",
                parent=self._styles["Normal"],
                fontSize=self.config.FONT_SIZE_SMALL,
                fontName="Helvetica-Bold",
                leading=11,
            )
        )

    def get_style(self, name: str) -> ParagraphStyle:
        """
        Retorna estilo pelo nome.

        Args:
            name: Nome do estilo (ex: 'Normal', 'BoldCenter', 'Small')

        Returns:
            ParagraphStyle: Estilo solicitado
        """
        return cast(ParagraphStyle, self._styles[name])

    def create_centered_style(
        self, font_size: int, bold: bool = False, leading: int | None = None
    ) -> ParagraphStyle:
        """
        Cria estilo centralizado customizado.

        Args:
            font_size: Tamanho da fonte
            bold: Se é negrito
            leading: Espaçamento entre linhas (opcional)

        Returns:
            ParagraphStyle: Estilo criado
        """
        name_suffix = "Bold" if bold else "Normal"
        name = f"Centered_{font_size}_{name_suffix}"

        if leading is None:
            leading = int(font_size * 1.2)

        return ParagraphStyle(
            name=name,
            parent=self._styles["Normal"],
            fontSize=font_size,
            alignment=TA_CENTER,
            fontName="Helvetica-Bold" if bold else "Helvetica",
            leading=leading,
        )

    def create_header_style(
        self, font_size: int, leading: int | None = None
    ) -> ParagraphStyle:
        """
        Cria estilo de cabeçalho centralizado e negrito.

        Args:
            font_size: Tamanho da fonte
            leading: Espaçamento entre linhas (opcional)

        Returns:
            ParagraphStyle: Estilo de cabeçalho
        """
        if leading is None:
            leading = int(font_size * 1.2)

        return ParagraphStyle(
            name=f"Header_{font_size}",
            parent=self._styles["Normal"],
            fontSize=font_size,
            alignment=TA_CENTER,
            fontName="Helvetica-Bold",
            leading=leading,
        )

    def create_table_header_style(self) -> ParagraphStyle:
        """
        Retorna estilo para cabeçalhos de tabela.

        Returns:
            ParagraphStyle: Estilo para títulos de colunas
        """
        return self.get_style("BoldSmall")

    def create_small_style(self) -> ParagraphStyle:
        """
        Retorna estilo para texto pequeno.

        Returns:
            ParagraphStyle: Estilo Small
        """
        return self.get_style("Small")

    def create_bold_small_style(self) -> ParagraphStyle:
        """
        Retorna estilo para texto pequeno em negrito.

        Returns:
            ParagraphStyle: Estilo BoldSmall
        """
        return self.get_style("BoldSmall")

    def create_bold_centered_style(self) -> ParagraphStyle:
        """
        Retorna estilo para texto centralizado em negrito.

        Returns:
            ParagraphStyle: Estilo BoldCenter
        """
        return self.get_style("BoldCenter")

    def create_proxima_retirada_style(self) -> ParagraphStyle:
        """
        Retorna estilo para a linha de próxima retirada no recibo.

        Usa o tamanho do cabeçalho incrementado em 2px para destacar.

        Returns:
            ParagraphStyle: Estilo para a próxima retirada
        """
        return ParagraphStyle(
            name="ProximaRetirada",
            parent=self._styles["Normal"],
            fontSize=14,
            alignment=TA_CENTER,
            fontName="Helvetica-Bold",
            leading=19,
        )

    def create_header_medium_style(self) -> ParagraphStyle:
        """
        Retorna estilo para cabeçalho médio.

        Returns:
            ParagraphStyle: Estilo HeaderMedium
        """
        return self.get_style("HeaderMedium")

    def create_normal_style(self) -> ParagraphStyle:
        """
        Retorna estilo normal.

        Returns:
            ParagraphStyle: Estilo Normal
        """
        return cast(ParagraphStyle, self._styles["Normal"])
