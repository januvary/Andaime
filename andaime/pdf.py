"""Operações de PDF compartilhadas entre os apps (BAP, Emissor, Negativas, ...).

Facade sobre as melhores bibliotecas por tarefa:

- estrutura (abrir, contar, dividir, mesclar, extrair página): ``pypdf``
- imagem -> PDF: ``img2pdf``
- rasterização: ``pypdfium2``
- criação de PDF (reportlab + svglib): ``DrawingFlowable``, ``load_svg_drawing``,
  ``PDFConfig``, ``PDFStyleManager``
"""

from __future__ import annotations

import io
import threading
from pathlib import Path
from typing import Iterable, Union

from PySide6.QtGui import QImage

# PDFium não é thread-safe; chamadas concorrentes corrompem o bitmap.
_PDFIUM_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Estrutura (pypdf)
# ---------------------------------------------------------------------------


def open_pdf(src: Union[bytes, str, Path]):
    """Abre um PDF (bytes ou caminho) como ``pypdf.PdfReader``."""
    from pypdf import PdfReader

    if isinstance(src, (str, Path)):
        return PdfReader(str(src))
    return PdfReader(io.BytesIO(src))


def page_count(src: Union[bytes, str, Path]) -> int:
    """Número de páginas do PDF."""
    return len(open_pdf(src).pages)


def split_pages(src: Union[bytes, str, Path]) -> list[bytes]:
    """Divide um PDF em N PDFs de página única."""
    from pypdf import PdfWriter

    reader = open_pdf(src)
    out: list[bytes] = []
    for i in range(len(reader.pages)):
        w = PdfWriter()
        w.add_page(reader.pages[i])
        buf = io.BytesIO()
        w.write(buf)
        out.append(buf.getvalue())
    return out


def extract_page(src: Union[bytes, str, Path], page: int) -> bytes:
    """Extrai uma única página como PDF de página única (bytes)."""
    from pypdf import PdfWriter

    reader = open_pdf(src)
    if not reader.pages:
        raise ValueError("PDF vazio")
    w = PdfWriter()
    w.add_page(reader.pages[page])
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def merge_pdfs(conteudos: Iterable[Union[bytes, str, Path]], output_path: str) -> str:
    """Concatena vários PDFs em um arquivo."""
    from pypdf import PdfWriter

    writer = PdfWriter()
    for blob in conteudos:
        if not blob:
            continue
        writer.append(open_pdf(blob))
    with open(output_path, "wb") as f:
        writer.write(f)
    return output_path


# ---------------------------------------------------------------------------
# Imagem -> PDF (img2pdf)
# ---------------------------------------------------------------------------


def _clamped_layout_fun(imgwidthpx, imgheightpx, ndpi):
    """Layout padrão do img2pdf com as dimensões limitadas a 3–14400 pt.

    O img2pdf aborta (via pikepdf) quando o DPI declarado — ou o tamanho em
    pixels — produz uma página fora do limite do PDF (3–14400 unidades):
    DPI absurdo (1, 9999), imagens minúsculas (ícones de poucos pixels) ou
    gigantes (panoramas). Aqui a página é escalada uniformemente para caber,
    preservando a proporção. Para imagens dentro do limite, o resultado é
    idêntico ao layout padrão.
    """
    import img2pdf  # type: ignore[import-untyped]

    pw, ph, iw, ih = img2pdf.default_layout_fun(imgwidthpx, imgheightpx, ndpi)
    scale = 1.0
    major = max(pw, ph)
    if major > 14400.0:
        scale = 14400.0 / major
    minor = min(pw, ph) * scale
    if 0 < minor < 3.0:
        scale *= 3.0 / minor
    if scale == 1.0:
        return pw, ph, iw, ih
    return pw * scale, ph * scale, iw * scale, ih * scale


def image_to_pdf(source: Union[bytes, str, Path]) -> bytes:
    """Converte uma imagem em PDF de página única.

    Usa um layout que limita a página ao intervalo exigido pelo PDF
    (3–14400 unidades): imagens com DPI corrompido ou dimensões extremas
    são escaladas em vez de abortar a conversão.
    """
    import img2pdf  # type: ignore[import-untyped]

    if isinstance(source, (str, Path)):
        raw = Path(source).read_bytes()
    else:
        raw = source
    return img2pdf.convert(raw, layout_fun=_clamped_layout_fun)


# ---------------------------------------------------------------------------
# Rasterização (pypdfium2)
# ---------------------------------------------------------------------------


def render_page_pil(
    src: Union[bytes, str, Path], page: int, scale: float = 2.0
):
    """Rasteriza uma página como ``PIL.Image`` (modo RGB)."""
    import pypdfium2 as pdfium  # type: ignore[import-untyped]
    from PIL import Image  # noqa: F401  (garante dependência disponível)

    with _PDFIUM_LOCK:
        doc = pdfium.PdfDocument(str(src) if isinstance(src, (str, Path)) else src)
        try:
            if len(doc) == 0:
                raise ValueError("PDF has no pages")

            page_index = page
            if page_index >= len(doc):
                page_index = 0

            pil = doc[page_index].render(scale=scale).to_pil()
        finally:
            doc.close()

    if pil.mode != "RGB":
        pil = pil.convert("RGB")
    return pil


def render_pages_pil(
    src: Union[bytes, str, Path], scale: float = 2.0
):
    """Rasteriza todas as páginas como ``list[PIL.Image]`` (uma abertura)."""
    import pypdfium2 as pdfium  # type: ignore[import-untyped]
    from PIL import Image  # noqa: F401

    out = []
    with _PDFIUM_LOCK:
        doc = pdfium.PdfDocument(str(src) if isinstance(src, (str, Path)) else src)
        try:
            for page in doc:
                pil = page.render(scale=scale).to_pil()
                if pil.mode != "RGB":
                    pil = pil.convert("RGB")
                out.append(pil)
        finally:
            doc.close()
    return out


def render_page(
    src: Union[bytes, str, Path], page: int, scale: float = 2.0
) -> QImage:
    """Rasteriza uma página como ``QImage`` (cópia própria do buffer)."""
    pil = render_page_pil(src, page, scale)
    data = pil.tobytes()
    qimg = QImage(
        data, pil.width, pil.height, pil.width * 3,
        QImage.Format.Format_RGB888,
    )
    return qimg.copy()


# ---------------------------------------------------------------------------
# Criação de PDF (reportlab + svglib)
# ---------------------------------------------------------------------------
#
# reportlab e svglib são importados sob demanda nas funções e classes abaixo.
# Apps que só usam manipulação de PDF (pypdf, img2pdf, pypdfium2) não pagam
# o custo de importação dessas bibliotecas.

# Constantes numéricas — evitam importar reportlab só para A4/cm.
A4_WIDTH: float = 595.2755905511812   # reportlab.lib.pagesizes.A4[0]
A4_HEIGHT: float = 841.8897637795275  # reportlab.lib.pagesizes.A4[1]
CM: float = 28.346456692913385        # 1 cm em pontos PDF


def _make_svg_flowable(drawing, offset_y: float = 0):
    """Cria um Flowable a partir de um ``reportlab.graphics.Drawing``.

    ``GraphicsFlowable`` foi removido no ReportLab 4.4.7; este wrapper
    substitui a funcionalidade.
    """
    from reportlab.platypus import Flowable

    class _DrawingFlowable(Flowable):
        def __init__(self, drawing, offset_y: float = 0) -> None:
            super().__init__()
            self.drawing = drawing
            self.offset_y = offset_y
            self.width = drawing.width
            self.height = drawing.height

        def wrap(self, aW: float, aH: float) -> tuple[float, float]:
            return (self.width, self.height)

        def draw(self) -> None:
            self.canv.saveState()
            self.canv.translate(0, -self.offset_y)
            self.drawing.drawOn(self.canv, 0, 0)
            self.canv.restoreState()

    return _DrawingFlowable(drawing, offset_y=offset_y)


def load_svg_drawing(
    svg_path: Union[str, Path],
    target_size: float,
    offset_y: float = 0,
):
    """Carrega um SVG e retorna um Flowable ReportLab escalado.

    Args:
        svg_path: Caminho para o arquivo SVG.
        target_size: Largura alvo em pontos (pt). A altura é calculada
            proporcionalmente.
        offset_y: Deslocamento vertical do Drawing (positivo = para baixo).

    Returns:
        Flowable pronto para uso em Platypus, ou ``None`` se o SVG não
        puder ser carregado.
    """
    from svglib.svglib import svg2rlg

    path = Path(svg_path)
    if not path.exists():
        return None

    drawing = svg2rlg(str(path))
    if drawing is None:
        return None

    original_width = drawing.width
    original_height = drawing.height

    if original_width <= 0:
        return None

    scale_factor = target_size / original_width
    drawing.scale(scale_factor, scale_factor)
    drawing.width = original_width * scale_factor
    drawing.height = original_height * scale_factor
    drawing.hAlign = "LEFT"
    drawing.vAlign = "BOTTOM"

    return _make_svg_flowable(drawing, offset_y=offset_y)


# ---------------------------------------------------------------------------
# Configuração e estilos base para criação de PDF (reportlab)
# ---------------------------------------------------------------------------


from dataclasses import dataclass


@dataclass
class PDFConfig:
    """Configurações base de layout para geração de PDF.

    Fornece constantes de página, margens, tamanhos de fonte e espaçamento.
    Apps devem herdar e adicionar colunas, cores ou configurações específicas.

    Não importa reportlab — ``pagesize`` é armazenado como tupla ``(w, h)``.
    """
    # Página — tupla (width, height) em pontos; padrão A4.
    pagesize: tuple[float, float] = (A4_WIDTH, A4_HEIGHT)
    margin: float = 0.7 * CM

    # Dimensões calculadas (preenchidas em __post_init__)
    width: float = 0
    height: float = 0
    total_width: float = 0

    # Tamanhos de fonte
    FONT_SIZE_SMALL: int = 9
    FONT_SIZE_NORMAL: int = 11
    FONT_SIZE_MEDIUM: int = 12
    FONT_SIZE_LARGE: int = 13

    # Espaçamento (padding)
    PADDING_SMALL: int = 2
    PADDING_MEDIUM: int = 3
    PADDING_LARGE: int = 4
    PADDING_XLARGE: int = 6
    PADDING_XXLARGE: int = 10

    # SVG
    LOGO_TARGET_SIZE: float = 1.8 * CM
    LOGO_OFFSET_Y: float = 0.0

    # Spacer
    SPACER_SMALL: int = 6

    def __post_init__(self) -> None:
        self.width, self.height = self.pagesize
        self.total_width = self.width - 2 * self.margin


class PDFStyleManager:
    """Gerenciador base de estilos Paragraph para ReportLab.

    Cria e gerencia ParagraphStyles usados na geração de PDF.  Apps podem
    herdar e adicionar estilos específicos via ``_setup_custom_styles``.
    """

    def __init__(self, config: PDFConfig) -> None:
        from reportlab.lib.styles import getSampleStyleSheet

        self.config = config
        self._styles = getSampleStyleSheet()
        self._setup_custom_styles()

    def _setup_custom_styles(self) -> None:
        """Cria estilos customizados.  Subclasses podem sobrescrever."""
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.enums import TA_CENTER

        fs = self.config.FONT_SIZE_NORMAL

        self._styles.add(ParagraphStyle(
            name="BoldCenter",
            parent=self._styles["Normal"],
            fontSize=fs,
            alignment=TA_CENTER,
            fontName="Helvetica-Bold",
            leading=14,
        ))
        self._styles.add(ParagraphStyle(
            name="HeaderLarge",
            parent=self._styles["Normal"],
            fontSize=self.config.FONT_SIZE_LARGE,
            alignment=TA_CENTER,
            fontName="Helvetica-Bold",
            leading=16,
        ))
        self._styles.add(ParagraphStyle(
            name="HeaderMedium",
            parent=self._styles["Normal"],
            fontSize=self.config.FONT_SIZE_MEDIUM,
            alignment=TA_CENTER,
            fontName="Helvetica-Bold",
            leading=14,
        ))
        self._styles.add(ParagraphStyle(
            name="Small",
            parent=self._styles["Normal"],
            fontSize=self.config.FONT_SIZE_SMALL,
            leading=11,
        ))
        self._styles.add(ParagraphStyle(
            name="BoldSmall",
            parent=self._styles["Normal"],
            fontSize=self.config.FONT_SIZE_SMALL,
            fontName="Helvetica-Bold",
            leading=11,
        ))

    def get_style(self, name: str):
        """Retorna estilo pelo nome."""
        return self._styles[name]

    def create_centered_style(self, font_size: int, bold: bool = False, leading: int | None = None):
        """Cria estilo centralizado customizado."""
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.enums import TA_CENTER

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

    def create_header_style(self, font_size: int, leading: int | None = None):
        """Cria estilo de cabeçalho centralizado e negrito."""
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.enums import TA_CENTER

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

    def create_normal_style(self):
        """Retorna estilo normal."""
        return self._styles["Normal"]
