"""Operações de PDF compartilhadas entre os apps (BAP, Emissor, ...).

Facade sobre as melhores bibliotecas por tarefa:

- estrutura (abrir, contar, dividir, mesclar, extrair página): ``pypdf``
- imagem -> PDF: ``img2pdf``
- rasterização: ``pypdfium2``
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
    from pypdf import PdfReader, PdfWriter

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
    from pypdf import PdfReader, PdfWriter

    reader = open_pdf(src)
    if not reader.pages:
        raise ValueError("PDF vazio")
    w = PdfWriter()
    w.add_page(reader.pages[page or 0])
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def merge_pdfs(conteudos: Iterable[Union[bytes, str, Path]], output_path: str) -> str:
    """Concatena vários PDFs em um arquivo."""
    from pypdf import PdfReader, PdfWriter

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
    import img2pdf

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


def image_to_pdf(source: Union[bytes, str, Path], filetype: str = "") -> bytes:
    """Converte uma imagem em PDF de página única.

    Usa um layout que limita a página ao intervalo exigido pelo PDF
    (3–14400 unidades): imagens com DPI corrompido ou dimensões extremas
    são escaladas em vez de abortar a conversão.
    """
    import img2pdf

    if isinstance(source, (str, Path)):
        with open(source, "rb") as f:
            raw = f.read()
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
    import pypdfium2 as pdfium
    from PIL import Image  # noqa: F401  (garante dependência disponível)

    with _PDFIUM_LOCK:
        doc = pdfium.PdfDocument(str(src) if isinstance(src, (str, Path)) else src)
        try:
            if len(doc) == 0:
                raise ValueError("PDF has no pages")
            
            page_index = page or 0
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
    import pypdfium2 as pdfium
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
