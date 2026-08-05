#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Serviço de digitalização via TWAIN/WIA, agnóstico de hardware."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Protocol, TYPE_CHECKING, runtime_checkable

if TYPE_CHECKING:
    from PIL import Image

from emissor.services.exceptions import EmissorError
from emissor.utils.net_io import atomic_write_path, network_mkdir
from emissor.utils.paths import resolve_archive_dir
from emissor.utils.security import sanitize_filename

SCAN_SUBFOLDER = "RECIBOS ASSINADOS"

_COLOR_MODE_TO_MODE = {
    "grayscale": "L",
    "color": "RGB",
    "bw": "1",
}


def _trim_white(img: "Image.Image") -> "Image.Image":
    """Crops fully-blank borders (rows/cols where every pixel is near-white).

    Only trims borders where *every* pixel is within the near-white threshold,
    so content is never touched. Safe to run unconditionally on every page.
    """
    from PIL import Image, ImageChops

    bg = Image.new(img.mode, img.size, 1 if img.mode == "1" else 255)
    diff = ImageChops.difference(img, bg).convert("L")
    bbox = diff.point(lambda x: 255 if x > 10 else 0).getbbox()
    if bbox:
        return img.crop(bbox)
    return img


def _normalize_pil_page(
    img: "Image.Image",
    dpi: int,
    flip_top_bottom: bool = False,
    flip_left_right: bool = False,
) -> "Image.Image":
    """Finaliza imagem PIL: força decode, carimba DPI e (opc.) desvira WIA."""
    from PIL import Image

    img.load()
    if flip_top_bottom:
        img = img.transpose(Image.FLIP_TOP_BOTTOM)
    if flip_left_right:
        img = img.transpose(Image.FLIP_LEFT_RIGHT)
    img = _trim_white(img)
    img.info["dpi"] = (dpi, dpi)
    return img


class ScannerError(EmissorError):
    """Erro genérico de digitalização."""


def resolve_scan_dir(
    save_root: Path,
    patient_tipo: str,
    patient_name: str,
) -> Path:
    """Resolve o diretório ``RECIBOS ASSINADOS`` do paciente (cria se falta)."""
    safe_patient_name = sanitize_filename(patient_name)
    archive_dir = resolve_archive_dir(
        save_root,
        patient_tipo,
        safe_patient_name,
        create=True,
    )
    scan_dir = archive_dir / SCAN_SUBFOLDER
    network_mkdir(scan_dir)
    return scan_dir


def next_scan_path(scan_dir: Path, date_str: str) -> Path:
    """Calcula o próximo caminho de scan: ``<DATA>.pdf`` ou ``<DATA>_NN.pdf``."""
    base = scan_dir / f"{date_str}.pdf"
    if not base.exists():
        return base

    index = 1
    while True:
        candidate = scan_dir / f"{date_str}_{index:02d}.pdf"
        if not candidate.exists():
            return candidate
        index += 1


@runtime_checkable
class ScannerBackend(Protocol):
    """Contrato mínimo de um backend de digitalização."""

    def list_sources(self) -> list[str]:
        """Lista os nomes das fontes (scanners) disponíveis."""
        ...

    def acquire(self, dpi: int, color_mode: str) -> list[Image.Image]:
        """Digitaliza e retorna uma lista de imagens (uma por página)."""
        ...


class TwainBackend:
    """Backend TWAIN via pacote ``twain`` (Windows, import preguiçoso)."""

    def __init__(self, source_name: str | None = None) -> None:
        """Inicializa o backend (source_name=None usa o padrão da UI)."""
        self._source_name = source_name

    def _import_twain(self) -> Any:
        try:
            import twain  # type: ignore
        except ImportError as e:
            raise ScannerError(
                "Driver TWAIN (twain) não disponível. "
                "A digitalização requer Windows com o driver do scanner instalado."
            ) from e
        if not hasattr(twain, "SourceManager"):
            raise ScannerError("twain instalado não expõe SourceManager.")
        return twain

    @staticmethod
    def is_available() -> bool:
        """Verifica se o backend TWAIN está realmente utilizável (silencioso)."""
        try:
            import twain  # type: ignore
        except Exception:
            return False
        if not hasattr(twain, "SourceManager"):
            return False
        try:
            sm = twain.SourceManager()
        except Exception:
            return False
        try:
            _ = list(sm.source_names)
        except Exception:
            return False
        finally:
            try:
                sm.close()
            except Exception:
                pass
        return True

    def list_sources(self) -> list[str]:
        twain = self._import_twain()
        try:
            sm = twain.SourceManager()
            return list(sm.source_names)
        except Exception as e:
            raise ScannerError(f"Falha ao enumerar scanners: {e}") from e

    @staticmethod
    def _try_set_cap(src: Any, name: str, value: Any) -> None:
        """Tenta setar uma capability; ignora se o driver não suporta."""
        try:
            src.set_capability(name, value)
        except Exception:
            pass

    def acquire(self, dpi: int, color_mode: str) -> list[Image.Image]:
        twain = self._import_twain()
        pixel_value = {"grayscale": "gray", "color": "rgb", "bw": "bw"}.get(
            color_mode, "gray"
        )
        try:
            sm = twain.SourceManager()
            src = sm.open_source(self._source_name)
            try:
                src.set_capability("x_resolution", dpi)
                src.set_capability("y_resolution", dpi)
                src.set_capability("pixel_type", pixel_value)

                # Suppress driver progress dialogs, post-scan preview, etc.
                # CAP_INDICATORS = no progress indicator.
                self._try_set_cap(src, "indicators", False)

                # Try low-level acquire pattern (request_acquire +
                # xfer_image_natively) which gives more control over driver
                # UI than the convenience acquire() wrapper.
                images = self._do_acquire(src, twain, dpi)
                return [img for img in images if img is not None]
            finally:
                try:
                    src.close()
                except Exception:
                    pass
                try:
                    sm.close()
                except Exception:
                    pass
        except ScannerError:
            raise
        except Exception as e:
            raise ScannerError(f"Falha ao digitalizar: {e}") from e

    @staticmethod
    def _do_acquire(src: Any, twain: Any, dpi: int) -> list[Image.Image]:
        """Estratégia de aquisição com fallback (low-level → acquire)."""
        if hasattr(src, "request_acquire") and hasattr(src, "xfer_image_natively"):
            return TwainBackend._acquire_low_level(src, twain, dpi)
        return src.acquire(show_ui=False, close_after=True)

    @staticmethod
    def _acquire_low_level(src: Any, twain: Any, dpi: int) -> list[Image.Image]:
        """Aquisição via triplet TWAIN (request_acquire → xfer_image_natively)."""
        from io import BytesIO

        src.request_acquire(show_ui=False, modal_ui=False)
        images: list[Image.Image] = []
        while True:
            try:
                handle, remaining = src.xfer_image_natively()
            except Exception:
                break
            if handle:
                try:
                    bmp_bytes = twain.dib_to_bm_file(handle)
                    from PIL import Image

                    img = Image.open(BytesIO(bmp_bytes))
                    images.append(_normalize_pil_page(img, dpi))
                except Exception:
                    pass
            if not remaining:
                break
        if not images:
            raise ScannerError(
                "Nenhuma imagem retornada pelo scanner (digitalização cancelada?)."
            )
        return images


class WiaBackend:
    """Backend WIA via COM (``comtypes``) — Windows, sem driver/admin."""

    # WIA property IDs.
    _WIA_IPS_CUR_INTENT = 6146
    _WIA_IPS_XRES = 6147
    _WIA_IPS_YRES = 6148
    _WIA_IPA_DATATYPE = 4103
    _WIA_DPS_DOCUMENT_HANDLING_STATUS = 3088
    _WIA_DPS_DOCUMENT_HANDLING_SELECT = 3087
    _FEEDER_SELECT = 0x001  # alimentador (ADF)
    _FLATBED_SELECT = 0x002  # vidro (flatbed)

    # WIA_IPA_DATATYPE values.
    _DATATYPE = {"bw": 0, "grayscale": 2, "color": 3}
    # WIA_IPS_CUR_INTENT values.
    _INTENT = {"bw": 4, "grayscale": 2, "color": 1}

    # WiaImgFmt_PNG / WiaImgFmt_BMP (fallback se o driver não suportar PNG).
    _FMT_PNG = "{B96B3CAF-0728-11D3-9D7B-0000C0A9F1C6}"
    _FMT_BMP = "{B96B3CAB-0728-11D3-9D7B-0000C0A9F1C6}"

    # WIA_DPS_DOCUMENT_HANDLING_STATUS bits.
    _FEEDER_LOADED = 0x01  # FEED_READY: há papel no alimentador (ADF).
    # WIA_DPS_DOCUMENT_HANDLING_CAPABILITIES (device prop 3086).
    _WIA_DPS_DOCUMENT_HANDLING_CAPABILITIES = 3086
    _FEEDER_CAP = 0x01  # dispositivo possui alimentador (ADF).

    # Limite de segurança para evitar loop infinito com ADF.
    _MAX_ADF_PAGES = 100

    def __init__(self, source_name: str | None = None) -> None:
        self._source_name = source_name

    @staticmethod
    def _device_manager():
        import comtypes.client  # runtime-only no Windows

        return comtypes.client.CreateObject("WIA.DeviceManager")

    @staticmethod
    def is_available() -> bool:
        """True se o COM do WIA puder ser instanciado (Windows c/ WIA)."""
        try:
            WiaBackend._device_manager()
            return True
        except Exception:
            return False

    def list_sources(self) -> list[str]:
        try:
            dm = self._device_manager()
            names = []
            for info in dm.DeviceInfos:
                try:
                    names.append(info.Properties["Name"].Value)
                except Exception:
                    pass
            return names
        except Exception as e:
            raise ScannerError(f"Falha ao enumerar scanners (WIA): {e}") from e

    def _connect_device(self, dm: Any) -> Any:
        """Conecta ao dispositivo (por nome, se fornecido; senão o 1º)."""
        chosen = None
        for info in dm.DeviceInfos:
            try:
                name = info.Properties["Name"].Value
            except Exception:
                name = ""
            if (not self._source_name) or (self._source_name in name):
                chosen = info
                break
        if chosen is None:
            try:
                chosen = dm.DeviceInfos[1]  # coleção WIA é 1-indexada
            except Exception as e:
                raise ScannerError("Nenhum scanner WIA encontrado.") from e
        return chosen.Connect()

    @staticmethod
    def _set_prop(props: Any, prop_id: int, value: Any) -> None:
        """Seta uma propriedade WIA; ignora se o dispositivo não suportar."""
        try:
            props.Item(prop_id).Value = value
        except Exception:
            pass

    @staticmethod
    def _get_prop(props: Any, prop_id: int) -> Any:
        try:
            return props.Item(prop_id).Value
        except Exception:
            return None

    def acquire(self, dpi: int, color_mode: str) -> list[Image.Image]:
        try:
            import comtypes  # noqa: F401
            import comtypes.client  # noqa: F401
        except Exception as e:
            raise ScannerError(
                "WIA indisponível: comtypes não pôde ser carregado."
            ) from e

        # WIA cria objetos COM: garante COM inicializado nesta thread
        # (o acquire roda numa QThread dedicada). WIA requer STA.
        co_initialized = False
        try:
            comtypes.CoInitializeEx(comtypes.COINIT_APARTMENTTHREADED)
            co_initialized = True
        except Exception:
            try:
                comtypes.CoInitialize()
                co_initialized = True
            except Exception:
                pass

        mode = color_mode if color_mode in self._DATATYPE else "grayscale"
        try:
            dm = self._device_manager()
            dev = self._connect_device(dm)
            item = dev.Items[1]

            props = item.Properties
            self._set_prop(props, self._WIA_IPA_DATATYPE, self._DATATYPE[mode])
            self._set_prop(props, self._WIA_IPS_CUR_INTENT, self._INTENT[mode])
            self._set_prop(props, self._WIA_IPS_XRES, int(dpi))
            self._set_prop(props, self._WIA_IPS_YRES, int(dpi))

            # Seleciona a fonte: alimentador (ADF) se disponível, senão vidro.
            # Sem isso, muitos drivers permanecem no flatbed e ignoram o ADF.
            feed_select = (
                self._FEEDER_SELECT if self._has_feeder(dev)
                else self._FLATBED_SELECT
            )
            self._set_prop(
                dev.Properties,
                self._WIA_DPS_DOCUMENT_HANDLING_SELECT,
                feed_select,
            )

            images = self._transfer_all(dev, item, dpi)
        except ScannerError:
            raise
        except Exception as e:
            raise ScannerError(f"Falha ao digitalizar (WIA): {e}") from e
        finally:
            if co_initialized:
                try:
                    comtypes.CoUninitialize()
                except Exception:
                    pass

        if not images:
            raise ScannerError(
                "Nenhuma imagem digitalizada (verifique o alimentador/vidro)."
            )
        return images

    def _has_feeder(self, dev: Any) -> bool:
        """True se o dispositivo declara possuir alimentador (ADF)."""
        cap = self._get_prop(
            dev.Properties, self._WIA_DPS_DOCUMENT_HANDLING_CAPABILITIES
        )
        try:
            return bool(cap is not None and (int(cap) & self._FEEDER_CAP))
        except Exception:
            return False

    def _feeder_has_more(self, dev: Any) -> bool:
        """True se ainda há papel no alimentador (bit FEED_READY)."""
        status = self._get_prop(
            dev.Properties, self._WIA_DPS_DOCUMENT_HANDLING_STATUS
        )
        try:
            return bool(status is not None and (int(status) & self._FEEDER_LOADED))
        except Exception:
            return False

    def _transfer_one(self, item: Any) -> Any:
        """Transfere 1 imagem (PNG; cai p/ BMP se o driver não suportar)."""
        try:
            return item.Transfer(self._FMT_PNG)
        except Exception:
            return item.Transfer(self._FMT_BMP)

    def _wia_img_to_pil(self, wia_img: Any, dpi: int = 200) -> Image.Image:
        from PIL import Image

        flip_tb = os.environ.get(
            "EMISSOR_SCAN_FLIP_TOP_BOTTOM", "1"
        ).strip() in ("1", "true", "True")
        flip_lr = os.environ.get(
            "EMISSOR_SCAN_FLIP_LEFT_RIGHT", "1"
        ).strip() in ("1", "true", "True")

        suffix = ".png"
        tmp = Path(tempfile.mktemp(suffix=suffix))
        try:
            wia_img.SaveFile(str(tmp))
            with Image.open(tmp) as src:
                img = src.copy()
        finally:
            tmp.unlink(missing_ok=True)

        # WIA entrega o DIB frequentemente invertido (topo/baixo e/ou esquerda/
        # direita) para vários drivers/ADF; corrige a orientação e carimba o DPI.
        return _normalize_pil_page(
            img, dpi, flip_top_bottom=flip_tb, flip_left_right=flip_lr
        )

    def _transfer_all(self, dev: Any, item: Any, dpi: int) -> list[Image.Image]:
        """Transfere páginas: 1 (flatbed) ou até esvaziar (ADF, com teto)."""
        images: list[Image.Image] = []

        # Flatbed / sem ADF: uma única página. Evita um 2º Transfer() que
        # pode bloquear ou re-digitalizar o vidro em certos drivers.
        if not self._has_feeder(dev):
            try:
                wia_img = self._transfer_one(item)
            except Exception:
                return images
            images.append(self._wia_img_to_pil(wia_img, dpi))
            return images

        # ADF: repete até o alimentador esvaziar (ou erro/limite).
        for _ in range(self._MAX_ADF_PAGES):
            if not self._feeder_has_more(dev):
                break
            try:
                wia_img = self._transfer_one(item)
            except Exception:
                # WIA_ERROR_PAPER_EMPTY → fim do lote.
                break
            images.append(self._wia_img_to_pil(wia_img, dpi))
        return images


class SimulatedBackend:
    """Backend simulado (imagens em branco) para testes/demonstração."""

    def __init__(self, pages: int = 2) -> None:
        """Inicializa o backend simulado."""
        self._pages = pages

    def list_sources(self) -> list[str]:
        return ["Simulado (sem hardware)"]

    def acquire(self, dpi: int, color_mode: str) -> list[Image.Image]:
        pil_mode = _COLOR_MODE_TO_MODE.get(color_mode, "L")
        size = (int(dpi * 1.5), int(dpi * 2.1))  # ~carta a 150% para parecer recibo
        images = []
        for i in range(self._pages):
            from PIL import Image

            img = Image.new(pil_mode, size, 255 if pil_mode != "1" else 1)
            images.append(_normalize_pil_page(img, dpi))
        return images


def _default_backend() -> ScannerBackend:
    """Seleciona o backend conforme ambiente (env var ``EMISSOR_SCAN_BACKEND``)."""
    import os
    import sys

    env = os.environ.get("EMISSOR_SCAN_BACKEND", "").lower()
    if env == "sim":
        return SimulatedBackend()
    if env == "wia":
        return WiaBackend()
    if env == "twain":
        return TwainBackend()

    if sys.platform.startswith("win"):
        if WiaBackend.is_available():
            return WiaBackend()
        if TwainBackend.is_available():
            return TwainBackend()
        # Nenhum disponível: retorna WIA para produzir erro amigável no uso.
        return WiaBackend()

    # Fora do Windows não há backend de hardware (WIA/TWAIN são Windows-only);
    # usa o backend simulado para permitir dev/teste do fluxo completo.
    return SimulatedBackend()


# Alias público (nome usado externamente/documentação).
get_backend = _default_backend


class ScannerService:
    """Serviço de digitalização: aquisição (backend) + gravação do PDF."""

    def __init__(
        self,
        save_root: Path,
        backend: ScannerBackend | None = None,
    ) -> None:
        """Inicializa o serviço (backend padrão: auto)."""
        self._save_root = Path(save_root)
        self._backend = backend or _default_backend()

    def list_sources(self) -> list[str]:
        """Lista scanners disponíveis."""
        return self._backend.list_sources()

    def scan_to_pdf(
        self,
        patient_tipo: str,
        patient_name: str,
        date_str: str,
        dpi: int = 200,
        color_mode: str = "grayscale",
    ) -> Path:
        """Digitaliza e salva o PDF no diretório do paciente (acquire + copy).

        Para uso assíncrono, chame ``acquire_locally()`` (thread da UI) e
        ``copy_to_network()`` (worker) separadamente.
        """
        local_tmp = self.acquire_locally(dpi=dpi, color_mode=color_mode)
        return self.copy_to_network(
            local_tmp=local_tmp,
            patient_tipo=patient_tipo,
            patient_name=patient_name,
            date_str=date_str,
        )

    def acquire_locally(
        self,
        dpi: int = 200,
        color_mode: str = "grayscale",
    ) -> Path:
        """Adquire imagens e salva PDF temporário local (thread da UI).

        Args:
            color_mode: "grayscale", "color" ou "bw"
        """
        images = self._backend.acquire(dpi=dpi, color_mode=color_mode)

        # Diagnóstico de campo: com EMISSOR_SCAN_DUMP=1, salva cada imagem
        # crua em %TEMP%/emissor_scan_dump/ + loga DPI/orientação. Útil pois
        # WIA só é validável na máquina-alvo (Windows + scanner real).
        if os.environ.get("EMISSOR_SCAN_DUMP", "").strip() in ("1", "true", "True"):
            try:
                self._dump_debug_images(images, dpi, color_mode)
            except Exception:
                pass

        if not images:
            raise ScannerError(
                "Nenhuma página digitalizada (scanner vazio ou cancelado)."
            )

        fd, name = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        local_tmp = Path(name)
        try:
            self._save_images_as_pdf(images, local_tmp, color_mode, dpi)
        except Exception as e:
            local_tmp.unlink(missing_ok=True)
            raise ScannerError(f"Falha ao salvar digitalização: {e}") from e

        return local_tmp

    def copy_to_network(
        self,
        local_tmp: Path,
        patient_tipo: str,
        patient_name: str,
        date_str: str,
    ) -> Path:
        """Copia PDF local para a rede (escrita atômica, worker thread)."""
        scan_dir = resolve_scan_dir(
            self._save_root,
            patient_tipo,
            patient_name,
        )
        out_path = next_scan_path(scan_dir, date_str)
        try:
            with atomic_write_path(out_path) as net_tmp:
                shutil.copy2(local_tmp, net_tmp)
        except OSError as e:
            raise ScannerError(
                f"Digitalização concluída mas falha ao salvar no destino: {e}. "
                f"Cópia temporária preservada em {local_tmp}."
            ) from e
        else:
            local_tmp.unlink(missing_ok=True)

        return out_path

    @staticmethod
    def _save_images_as_pdf(
        images: list[Image.Image],
        out_path: Path,
        color_mode: str,
        dpi: int,
    ) -> None:
        """Salva uma lista de imagens como PDF multipágina."""
        pil_mode = _COLOR_MODE_TO_MODE.get(color_mode, "L")
        converted = []
        for img in images:
            im = _normalize_pil_page(img.convert(pil_mode), dpi)
            converted.append(im)
        first, rest = converted[0], converted[1:]
        first.save(
            str(out_path),
            "PDF",
            resolution=dpi,
            save_all=True,
            append_images=rest,
        )

    @staticmethod
    def _dump_debug_images(
        images: list[Image.Image], dpi: int, color_mode: str
    ) -> None:
        """Salva imagens cruas em %TEMP%/emissor_scan_dump para depuração."""
        import tempfile

        dump_dir = Path(tempfile.gettempdir()) / "emissor_scan_dump"
        dump_dir.mkdir(parents=True, exist_ok=True)
        for i, img in enumerate(images, 1):
            p = dump_dir / f"page_{i:02d}.png"
            img.save(str(p))
        log = dump_dir / "scan_info.txt"
        info = [
            f"pages={len(images)}",
            f"requested_dpi={dpi}",
            f"color_mode={color_mode}",
        ]
        for i, img in enumerate(images, 1):
            info.append(
                f"page_{i}: size={img.size} mode={img.mode} "
                f"dpi={img.info.get('dpi')}"
            )
        log.write_text("\n".join(info))

