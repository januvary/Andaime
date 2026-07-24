#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Serviço de impressão silenciosa de PDFs multiplataforma com fallback."""

from __future__ import annotations

import os
import subprocess
import sys
from ctypes import Structure, c_int, c_uint, c_wchar_p
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from PIL import Image


# Estrutura DOCINFO do GDI para StartDocW. Definida em módulo (ctypes é
# multiplataforma; windll só existe no Windows, mas _DOCINFO em si não toca gdi32).
class _DOCINFO(Structure):
    """DOCINFOW — metadados de um trabalho de impressão GDI."""

    _fields_ = [
        ("cbSize", c_int),
        ("lpszDocName", c_wchar_p),
        ("lpszOutput", c_wchar_p),
        ("lpszDatatype", c_wchar_p),
        ("fwType", c_uint),
    ]


def _load_gdi() -> Any:
    """Carrega gdi32 via ctypes (Windows apenas)."""
    import ctypes

    return ctypes.windll.gdi32  # type: ignore[attr-defined]


# ============================================================================
# Resultado
# ============================================================================


class PrintStatus(Enum):
    """Estado terminal de uma tentativa de impressão.

    SPOOLED indica que o spooler aceitou o trabalho, não que o papel saiu.
    """

    SPOOLED = "spooled"
    NO_PRINTER = "no_printer"
    PRINTER_NOT_READY = "printer_not_ready"
    RENDER_FAILED = "render_failed"
    SPOOL_FAILED = "spool_failed"
    UNSUPPORTED_OS = "unsupported_os"


# Mensagens voltadas ao usuário, indexadas por status.
_STATUS_MESSAGES: dict[PrintStatus, str] = {
    PrintStatus.SPOOLED: "Enviado para impressão.",
    PrintStatus.NO_PRINTER: "Nenhuma impressora padrão configurada.",
    PrintStatus.PRINTER_NOT_READY: "Impressora indisponível.",
    PrintStatus.RENDER_FAILED: "Falha ao renderizar o PDF para impressão.",
    PrintStatus.SPOOL_FAILED: "Falha ao enviar o trabalho para a impressora.",
    PrintStatus.UNSUPPORTED_OS: "Impressão automática não suportada neste sistema.",
}


@dataclass(frozen=True)
class PrintResult:
    """Resultado imutável de uma tentativa de impressão."""

    status: PrintStatus
    message: str
    pdf_path: str
    printer: str | None
    copies: int
    backend: str

    @property
    def ok(self) -> bool:
        """True se o trabalho foi spoolado com sucesso."""
        return self.status is PrintStatus.SPOOLED


# ============================================================================
# Backends
# ============================================================================


class PrinterBackend(Protocol):
    """Contrato para um backend de impressão."""

    name: str

    def spool(self, pdf_path: str, copies: int, job_title: str) -> PrintResult:
        """Spoola o PDF para a impressora."""
        ...


# --- Windows (primário) -----------------------------------------------------


# Flags de status de win32print que indicam impressora indisponível.
# Mantidos como int para evitar importar win32print fora do Windows.
_PRINTER_STATUS_OFFLINE = 0x00000080
_PRINTER_STATUS_ERROR = 0x00000002
_PRINTER_STATUS_PAPER_JAM = 0x00000008
_PRINTER_STATUS_PAPER_OUT = 0x00000010
_PRINTER_STATUS_DOOR_OPEN = 0x40000000
_PRINTER_STATUS_NOT_AVAILABLE = 0x00001000

_PRINTER_PROBLEM_FLAGS = (
    _PRINTER_STATUS_OFFLINE
    | _PRINTER_STATUS_ERROR
    | _PRINTER_STATUS_PAPER_JAM
    | _PRINTER_STATUS_PAPER_OUT
    | _PRINTER_STATUS_DOOR_OPEN
    | _PRINTER_STATUS_NOT_AVAILABLE
)

_PRINTER_PROBLEM_LABELS: dict[int, str] = {
    _PRINTER_STATUS_OFFLINE: "offline",
    _PRINTER_STATUS_ERROR: "erro",
    _PRINTER_STATUS_PAPER_JAM: "papel atolado",
    _PRINTER_STATUS_PAPER_OUT: "sem papel",
    _PRINTER_STATUS_DOOR_OPEN: "tampa aberta",
    _PRINTER_STATUS_NOT_AVAILABLE: "indisponível",
}

# Índices GetDeviceCaps (wingdi.h) para o cálculo da geometria da página.
# A área física (PHYSICALWIDTH/HEIGHT) é a folha inteira; a área útil
# (HORZRES/VERTRES) exclui as margens de hardware e começa em
# (PHYSICAL_OFFSET_X/Y).
_HORZRES = 8
_VERTRES = 10
_PHYSICAL_WIDTH = 110
_PHYSICAL_HEIGHT = 111
_PHYSICAL_OFFSET_X = 112
_PHYSICAL_OFFSET_Y = 113

# Modo de stretch para SetStretchBltMode: melhor qualidade ao redimensionar.
_HALFTONE_STRETCH = 4


def _describe_printer_problem(status_flags: int) -> str:
    """Traduz flags de status da impressora para texto em português."""
    labels = [
        label for flag, label in _PRINTER_PROBLEM_LABELS.items() if status_flags & flag
    ]
    return ", ".join(labels)


class Win32SpoolerBackend:
    """Backend primário no Windows: PDFium + GDI via win32print.

    Emite todas as cópias em um único StartDoc/EndDoc (trabalho collated).
    """

    name = "win32_spooler"

    def __init__(self, dpi: int = 300) -> None:
        """Inicializa o backend (dpi default 300)."""
        self._dpi = dpi

    def spool(self, pdf_path: str, copies: int, job_title: str) -> PrintResult:
        """Spoola o PDF para a impressora padrão do Windows."""
        import win32print

        try:
            printer_name = win32print.GetDefaultPrinter()
        except Exception:
            return PrintResult(
                status=PrintStatus.NO_PRINTER,
                message=_STATUS_MESSAGES[PrintStatus.NO_PRINTER],
                pdf_path=pdf_path,
                printer=None,
                copies=copies,
                backend=self.name,
            )

        if not printer_name:
            return PrintResult(
                status=PrintStatus.NO_PRINTER,
                message=_STATUS_MESSAGES[PrintStatus.NO_PRINTER],
                pdf_path=pdf_path,
                printer=None,
                copies=copies,
                backend=self.name,
            )

        problema = self._check_printer_ready(win32print, printer_name)
        if problema is not None:
            return PrintResult(
                status=PrintStatus.PRINTER_NOT_READY,
                message=f"Impressora indisponível: {problema}.",
                pdf_path=pdf_path,
                printer=printer_name,
                copies=copies,
                backend=self.name,
            )

        pages = self._render_pages(pdf_path)
        if pages is None:
            return PrintResult(
                status=PrintStatus.RENDER_FAILED,
                message=_STATUS_MESSAGES[PrintStatus.RENDER_FAILED],
                pdf_path=pdf_path,
                printer=printer_name,
                copies=copies,
                backend=self.name,
            )

        try:
            self._spool_pages(printer_name, pages, copies, job_title)
        except Exception:
            return PrintResult(
                status=PrintStatus.SPOOL_FAILED,
                message=_STATUS_MESSAGES[PrintStatus.SPOOL_FAILED],
                pdf_path=pdf_path,
                printer=printer_name,
                copies=copies,
                backend=self.name,
            )
        finally:
            for page in pages:
                page.close()

        return PrintResult(
            status=PrintStatus.SPOOLED,
            message=_STATUS_MESSAGES[PrintStatus.SPOOLED],
            pdf_path=pdf_path,
            printer=printer_name,
            copies=copies,
            backend=self.name,
        )

    def _check_printer_ready(self, win32print: object, printer_name: str) -> str | None:
        """Verifica se a impressora está pronta (best-effort, nunca levanta)."""
        open_printer = getattr(win32print, "OpenPrinter")
        close_printer = getattr(win32print, "ClosePrinter")
        get_printer = getattr(win32print, "GetPrinter")
        try:
            handle = open_printer(printer_name)
        except Exception:
            return None

        try:
            info = get_printer(handle, 2)
        except Exception:
            return None
        finally:
            close_printer(handle)

        status_flags = int(info.get("Status", 0)) if isinstance(info, dict) else 0
        if status_flags & _PRINTER_PROBLEM_FLAGS:
            return _describe_printer_problem(status_flags) or "indisponível"
        return None

    def _render_pages(self, pdf_path: str) -> list[Image.Image] | None:
        """Renderiza todas as páginas do PDF para imagens PIL otimizadas."""
        try:
            from andaime.pdf import render_pages_pil

            scale = self._dpi / 72.0
            return [
                self._optimize_for_print(pil)
                for pil in render_pages_pil(pdf_path, scale=scale)
            ]
        except Exception:
            return None

    @staticmethod
    def _optimize_for_print(img: Image.Image) -> Image.Image:
        """Otimiza a imagem: RGB se colorida, "L" se cinza/P&B."""
        if Win32SpoolerBackend._has_color(img):
            return img.convert("RGB")
        return img.convert("L")

    @staticmethod
    def _has_color(img: Image.Image) -> bool:
        """Detecta se a imagem tem cor cromática (não-cinza)."""
        if img.mode not in ("RGB", "RGBA"):
            return False
        from PIL import ImageChops

        channels = img.split()
        # difference() realça |R-G| e |G-B|; getbbox() devolve None só se a
        # imagem for toda uniforme (zero). Qualquer pixel diferindo -> bbox.
        diff_rg = ImageChops.difference(channels[0], channels[1]).getbbox()
        diff_gb = ImageChops.difference(channels[1], channels[2]).getbbox()
        return diff_rg is not None or diff_gb is not None

    @staticmethod
    def _spool_pages(
        printer_name: str,
        pages: list[Image.Image],
        copies: int,
        job_title: str,
    ) -> None:
        """Spoola páginas via GDI bruto (ctypes + gdi32), trabalho collated.

        Desenha cada página na *área imprimível* (HORZRES×VERTRES no offset de
        hardware), preservando a proporção e centralizando. Isso garante que
        nada caia na margem física não-imprimível da impressora.
        """
        from ctypes import byref, sizeof
        from contextlib import suppress

        from PIL import ImageWin

        gdi = _load_gdi()

        hdc = gdi.CreateDCW(c_wchar_p("WINSPOOL"), c_wchar_p(printer_name), None, None)
        if not hdc:
            raise RuntimeError(f"CreateDCW retornou HDC nulo para '{printer_name}'")
        try:
            with suppress(Exception):
                gdi.SetStretchBltMode(hdc, _HALFTONE_STRETCH)

            offset_x = gdi.GetDeviceCaps(hdc, _PHYSICAL_OFFSET_X)
            offset_y = gdi.GetDeviceCaps(hdc, _PHYSICAL_OFFSET_Y)
            printable_w = gdi.GetDeviceCaps(hdc, _HORZRES)
            printable_h = gdi.GetDeviceCaps(hdc, _VERTRES)

            # Preserva proporção da imagem e centraliza na área imprimível.
            img_w, img_h = pages[0].size
            scale = min(printable_w / img_w, printable_h / img_h)
            draw_w = int(img_w * scale)
            draw_h = int(img_h * scale)
            draw_x = offset_x + (printable_w - draw_w) // 2
            draw_y = offset_y + (printable_h - draw_h) // 2
            box = (draw_x, draw_y, draw_x + draw_w, draw_y + draw_h)

            docinfo = _DOCINFO(sizeof(_DOCINFO), job_title, None, None, 0)
            if gdi.StartDocW(hdc, byref(docinfo)) <= 0:
                raise RuntimeError("StartDocW falhou")

            dibs = [ImageWin.Dib(page) for page in pages]
            try:
                for _ in range(copies):
                    for dib in dibs:
                        if gdi.StartPage(hdc) <= 0:
                            raise RuntimeError("StartPage falhou")
                        dib.draw(hdc, box)
                        if gdi.EndPage(hdc) <= 0:
                            raise RuntimeError("EndPage falhou")
                gdi.EndDoc(hdc)
            except Exception:
                with suppress(Exception):
                    gdi.AbortDoc(hdc)
                raise
        finally:
            gdi.DeleteDC(hdc)


# --- Linux (melhor esforço, caixa de desenvolvimento) ----------------------


class LprBackend:
    """Backend de melhor esforço para Linux via lpr (N trabalhos separados)."""

    name = "lpr"

    # Timeout em segundos para esperar o lpr retornar.
    TIMEOUT = 10

    def spool(self, pdf_path: str, copies: int, job_title: str) -> PrintResult:
        """Spoola o PDF via lpr (espera término, checa returncode)."""
        try:
            cmd = ["lpr", "-J", job_title]
            for _ in range(max(1, copies)):
                cmd.append(pdf_path)
            # DEVNULL (não PIPE): se lpr escrever muito em stdout/stderr,
            # PIPE pode encher o buffer e deadlockar o wait(). lpr é silencioso,
            # mas DEVNULL remove qualquer risco sem perder diagnóstico de returncode.
            proc = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            try:
                proc.wait(timeout=self.TIMEOUT)
            except subprocess.TimeoutExpired:
                proc.kill()
                return PrintResult(
                    status=PrintStatus.SPOOL_FAILED,
                    message=_STATUS_MESSAGES[PrintStatus.SPOOL_FAILED],
                    pdf_path=pdf_path,
                    printer=None,
                    copies=copies,
                    backend=self.name,
                )
            if proc.returncode != 0:
                return PrintResult(
                    status=PrintStatus.SPOOL_FAILED,
                    message=_STATUS_MESSAGES[PrintStatus.SPOOL_FAILED],
                    pdf_path=pdf_path,
                    printer=None,
                    copies=copies,
                    backend=self.name,
                )
            return PrintResult(
                status=PrintStatus.SPOOLED,
                message=_STATUS_MESSAGES[PrintStatus.SPOOLED],
                pdf_path=pdf_path,
                printer=None,
                copies=copies,
                backend=self.name,
            )
        except FileNotFoundError:
            return PrintResult(
                status=PrintStatus.UNSUPPORTED_OS,
                message=_STATUS_MESSAGES[PrintStatus.UNSUPPORTED_OS],
                pdf_path=pdf_path,
                printer=None,
                copies=copies,
                backend=self.name,
            )


# ============================================================================
# Entry point
# ============================================================================


def _is_windows() -> bool:
    """True se rodando no Windows."""
    return sys.platform == "win32"


def _select_backends() -> list[PrinterBackend]:
    """Seleciona backends ativos conforme a plataforma."""
    if _is_windows():
        return [Win32SpoolerBackend()]
    return [LprBackend()]


def print_pdf(
    pdf_path: str | Path,
    copies: int = 1,
    job_title: str = "Emissor",
) -> PrintResult:
    """Imprime um PDF silenciosamente com verificação e fallback honesto.

    Nunca levanta exceção — todo erro vira PrintResult para a UI tratar.
    """
    path_str = str(pdf_path)
    safe_copies = max(1, copies)

    if not os.path.exists(path_str):
        return PrintResult(
            status=PrintStatus.RENDER_FAILED,
            message=f"Arquivo não encontrado: {path_str}",
            pdf_path=path_str,
            printer=None,
            copies=safe_copies,
            backend="precheck",
        )

    backends = _select_backends()
    last_result: PrintResult | None = None
    for backend in backends:
        result = backend.spool(path_str, safe_copies, job_title)
        if result.ok:
            return result
        last_result = result
        # Falhas terminais que não fazem sentido tentar outro backend.
        if result.status in (PrintStatus.NO_PRINTER, PrintStatus.PRINTER_NOT_READY):
            return result

    if last_result is not None:
        return last_result

    return PrintResult(
        status=PrintStatus.UNSUPPORTED_OS,
        message=_STATUS_MESSAGES[PrintStatus.UNSUPPORTED_OS],
        pdf_path=path_str,
        printer=None,
        copies=safe_copies,
        backend="precheck",
    )
