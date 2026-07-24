from __future__ import annotations

import copy
import io
from typing import Callable
from pathlib import Path
from contextlib import contextmanager

from PySide6.QtCore import (
    Qt,
    QSize,
    QMimeData,
    QPoint,
    Signal,
    QThreadPool,
    QRunnable,
    QObject,
    QTimer,
)
from PySide6.QtGui import (
    QPixmap,
    QImage,
    QIcon,
    QDrag,
)
from PySide6.QtWidgets import (
    QWidget,
    QGridLayout,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QFileDialog,
    QSizePolicy,
    QApplication,
    QGraphicsOpacityEffect,
)

from bap.ui_qt.styles import colors, get_theme
from bap.constants import DOC_TYPE_LABELS, DOC_TYPE_ORDER
from bap.models import GridItem
from bap.ui_qt.widgets.viewer_popup import (
    ViewerPopup,
    _build_classify_menu,
    _resolve_item_page,
)

_ICON_DIR = Path(__file__).resolve().parent.parent / "img"


def _icon_path(base: str) -> str:
    suffix = "-white" if get_theme() == "dark" else ""
    return str(_ICON_DIR / f"{base}{suffix}.svg")


class _Tile(QWidget):
    _INTERNAL_MIME = "application/x-ss54-doc"

    def __init__(self, item: GridItem, pixmap: "QPixmap | None", grid, on_open, on_remove, on_classify, parent=None):
        super().__init__(parent)
        self._item = item
        self._grid = grid
        self._on_open = on_open
        self._on_remove = on_remove
        self._on_classify = on_classify
        self._drag_start = None
        self._ghost = False
        self._pixmap = pixmap

        self.setFixedSize(140, 140)
        self.setAcceptDrops(True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._normal_style = (
            f"_Tile {{ background: {colors()['panel_bg']}; "
            f"border: 1px solid {colors()['panel_border']}; "
            f"border-radius: 6px; }}"
            f"_Tile:hover {{ border: 1px solid {colors()['text_dim']}; }}"
        )
        self._ghost_style = (
            f"_Tile {{ background: {colors()['panel_bg']}; "
            f"border: 2px dotted {colors()['text_dim']}; "
            f"border-radius: 6px; }}"
        )
        self.setStyleSheet(self._normal_style)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        thumb = QLabel()
        thumb.setFixedSize(138, 138)
        thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thumb.setStyleSheet("background: transparent; border: none;")
        self._thumb = thumb
        if self._pixmap is not None:
            self._update_thumb()
        else:
            # Miniatura carregada de forma assíncrona (fora da thread da UI)
            # para não bloquear o drop/recarregamento em documentos grandes.
            self._grid.request_thumbnail(self._item, self)
        layout.addWidget(thumb, alignment=Qt.AlignmentFlag.AlignCenter)

        copy_btn = QPushButton(self)
        open_btn = QPushButton(self)
        rotate_btn = QPushButton(self)
        remove_btn = QPushButton(self)
        copy_btn.setIcon(QIcon(_icon_path("copy-icon")))
        open_btn.setIcon(QIcon(_icon_path("preview-icon")))
        rotate_btn.setIcon(QIcon(_icon_path("rotate-icon")))
        remove_btn.setIcon(QIcon(_icon_path("X-icon")))

        # Botões de ícone da tile: transparentes, com borda e padding zero
        # (para caber o glifo 16x16 em 26x22). Reaproveita as cores do tema.
        btn_style = (
            "QPushButton {"
            " background: transparent;"
            f" border: 1px solid {colors()['panel_border']};"
            " border-radius: 4px; padding: 0px;"
            f" color: {colors()['text']}; }}"
            " QPushButton:hover {"
            f" background: {colors()['bg_hover']};"
            f" border: 1px solid {colors()['text_dim']}; }}"
        )
        for btn in (copy_btn, open_btn, rotate_btn, remove_btn):
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedSize(26, 22)
            btn.setIconSize(QSize(16, 16))
            btn.setStyleSheet(btn_style)
            btn.hide()

        copy_btn.setToolTip("Copiar imagem")
        open_btn.setToolTip("Abrir pré-visualização")
        rotate_btn.setToolTip("Girar 90°")
        remove_btn.setToolTip("Remover")

        copy_btn.clicked.connect(self._copy)
        open_btn.clicked.connect(lambda _checked=False: self._on_open(self._item))
        rotate_btn.clicked.connect(self._rotate)
        remove_btn.clicked.connect(lambda _checked=False: self._on_remove(self._item))

        rotate_btn.move(6, 112)
        copy_btn.move(40, 112)
        open_btn.move(74, 112)
        remove_btn.move(108, 112)
        for btn in (copy_btn, open_btn, rotate_btn, remove_btn):
            btn.raise_()

        self._action_btns = [copy_btn, open_btn, rotate_btn, remove_btn]

        self._badge = QLabel(self)
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._badge.setStyleSheet(
            "QLabel {"
            " background: rgba(0, 0, 0, 160);"
            " color: #ffffff;"
            " border-radius: 4px;"
            " padding: 2px 6px;"
            " font-size: 10px;"
            " }"
        )
        self._badge.setMaximumWidth(128)
        self._update_badge()

    def _update_thumb(self) -> None:
        self._thumb.setPixmap(
            self._pixmap.scaled(
                124, 124,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
        )

    def set_pixmap(self, pixmap: QPixmap) -> None:
        """Aplica uma miniatura renderizada fora da thread da UI."""
        if pixmap.isNull():
            return
        self._pixmap = pixmap
        self._update_thumb()

    def _rotate(self) -> None:
        if self._grid.rotate_item(self._item):
            self._pixmap = self._grid._thumb_for(self._item)
            self._update_thumb()

    def _update_badge(self):
        doc_type = self._item.tipo_documento
        if doc_type and doc_type != "outro":
            label = DOC_TYPE_LABELS.get(doc_type, doc_type)
            metrics = self._badge.fontMetrics()
            elided = metrics.elidedText(
                label, Qt.TextElideMode.ElideRight, 116
            )
            self._badge.setText(elided)
            self._badge.adjustSize()
            self._badge.move(4, 4)
            self._badge.show()
            self._badge.raise_()
        else:
            self._badge.hide()

    def contextMenuEvent(self, event):
        current = self._item.tipo_documento
        menu = _build_classify_menu(
            self,
            current=current,
            exclusions=self._grid._doc_exclusions,
            on_classify=self._do_classify,
        )
        menu.exec(event.globalPos())

    def _do_classify(self, doc_type: str) -> None:
        self._on_classify(self._item, doc_type)
        self._update_badge()

    def set_ghost(self, on: bool):
        if on == self._ghost:
            return
        self._ghost = on
        self.setStyleSheet(self._ghost_style if on else self._normal_style)
        if on:
            effect = QGraphicsOpacityEffect(self)
            effect.setOpacity(0.4)
            self.setGraphicsEffect(effect)
            for btn in self._action_btns:
                btn.hide()
        else:
            self.setGraphicsEffect(None)

    def _over_button(self, event) -> bool:
        return isinstance(self.childAt(event.pos()), QPushButton)

    def enterEvent(self, event):
        for btn in self._action_btns:
            btn.show()
        super().enterEvent(event)

    def leaveEvent(self, event):
        for btn in self._action_btns:
            btn.hide()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and not self._over_button(event):
            self._drag_start = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (
            self._drag_start is not None
            and event.buttons() & Qt.MouseButton.LeftButton
            and (event.pos() - self._drag_start).manhattanLength()
            >= QApplication.startDragDistance()
        ):
            self._drag_start = None
            self._start_drag()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_start = None
        super().mouseReleaseEvent(event)

    def _start_drag(self):
        self._grid.begin_drag(self._item)
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(self._INTERNAL_MIME, b"1")
        drag.setMimeData(mime)
        pix = self._pixmap.scaled(
            90, 90,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        if not pix.isNull():
            drag.setPixmap(pix)
            drag.setHotSpot(QPoint(pix.width() // 2, pix.height() // 2))
        drag.exec(Qt.DropAction.MoveAction)
        self._grid.end_drag()

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(self._INTERNAL_MIME):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(self._INTERNAL_MIME):
            event.acceptProposedAction()
            self._grid.drag_move_to(self._item)
        else:
            event.ignore()

    def dropEvent(self, event):
        if event.mimeData().hasFormat(self._INTERNAL_MIME):
            event.acceptProposedAction()
            self._grid.end_drag()
        else:
            event.ignore()

    def _copy(self):
        pix = self._pixmap
        if not pix.isNull():
            QApplication.clipboard().setPixmap(pix)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_open(self._item)


class _AddTile(QWidget):
    """Tile always-visible (último da grade) que abre o seletor de arquivos."""

    def __init__(self, on_add, parent=None):
        super().__init__(parent)
        self._on_add = on_add
        self.setFixedSize(140, 140)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._plus = QLabel("+")
        self._plus.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._plus, alignment=Qt.AlignmentFlag.AlignCenter)
        self.apply_theme()

    def apply_theme(self):
        c = colors()
        self.setStyleSheet(
            f"_AddTile {{ background: {c['panel_bg']}; "
            f"border: 1px dashed {c['panel_border']}; "
            f"border-radius: 6px; }}"
            f"_AddTile:hover {{ border: 1px dashed {c['text_dim']}; }}"
        )
        self._plus.setStyleSheet(
            f"color: {c['text_dim']}; font-size: 44px; font-weight: 300; "
            f"border: none; background: transparent;"
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_add()
        super().mousePressEvent(event)


@contextmanager
def _source_pdf(item: GridItem, loader: "Callable[[GridItem], bytes | None] | None" = None):
    """Abre o conteúdo de um item como um ``pypdf.PdfReader`` (context manager).

    Delega a resolução da fonte (``data``/``path``/``arquivo_id``) para
    :meth:`GridItem.open_document`. O leitor é fechado ao sair do contexto.
    ``None`` é produzido quando não há conteúdo útil.
    """
    doc = item.open_document(loader)
    if doc is None:
        yield None
        return
    try:
        yield doc
    finally:
        doc.close()


def _thumbnail(
    item: GridItem, loader: "Callable[[GridItem], bytes | None] | None" = None
) -> QPixmap:
    with _resolve_item_page(item, loader, scale=0.5) as (qimage, image_path):
        if qimage is not None:
            return QPixmap.fromImage(qimage)
        if image_path is not None:
            img = QImage(image_path)
            return QPixmap() if img.isNull() else QPixmap.fromImage(img)
        return QPixmap()


def _iter_zip_files(path: str):
    """Produz ``(nome, bytes)`` para cada arquivo útil de um ZIP.

    Ignora diretórios, entradas ocultas e o lixo de compactação do macOS
    (``__MACOSX/``, ``.DS_Store``, dotfiles). As entradas saem ordenadas por
    nome para dar uma ordem de páginas determinística.
    """
    import zipfile

    with zipfile.ZipFile(path) as zf:
        for info in sorted(zf.infolist(), key=lambda i: i.filename):
            name = info.filename
            if info.is_dir():
                continue
            base = name.rsplit("/", 1)[-1]
            if not base or base.startswith(".") or "__MACOSX/" in name:
                continue
            yield base, zf.read(info)


def _archive_to_items(path: str) -> list[GridItem]:
    """Expande um ZIP em itens de grade (Option B: tudo em memória).

    Cada imagem vira um PDF de página única (``data``); cada PDF interno é
    O nome
    original da entrada é preservado em ``arquivo_original``. Entradas que não
    podem ser decodificadas são silenciosamente ignoradas.
    """
    from bap.utils.archive_migrate import IMAGE_EXT
    from bap.models import image_to_pdf_bytes
    from andaime.pdf import split_pages

    items: list[GridItem] = []
    for name, raw in _iter_zip_files(path):
        ext = Path(name).suffix.lower()
        try:
            if ext == ".pdf":
                for pdf_bytes in split_pages(raw):
                    items.append(
                        GridItem(data=pdf_bytes, page=0, arquivo_original=name)
                    )
            elif ext in IMAGE_EXT:
                pdf_bytes = image_to_pdf_bytes(raw, ext[1:])
                items.append(
                    GridItem(data=pdf_bytes, page=0, arquivo_original=name)
                )
        except Exception:  # noqa: BLE001 — entrada corrompida/ilegível: pula
            continue
    return items


class _ThumbnailSignal(QObject):
    """Sinal isolado para entregar a miniatura renderizada à tile (thread-safe)."""

    ready = Signal(object, QPixmap)  # (item, pixmap)


class _ThumbnailTask(QRunnable):
    """Renderiza a miniatura de um item fora da thread da UI."""

    def __init__(self, item: GridItem, loader, signal: _ThumbnailSignal):
        super().__init__()
        self._item = item
        self._loader = loader
        self._signal = signal

    def run(self) -> None:
        pixmap = _thumbnail(self._item, self._loader)
        # Mesmo que a tile tenha sido removida, o sinal é ignorado pelo
        # destinatário (ver ``DocumentGrid._on_thumbnail_ready``).
        self._signal.ready.emit(self._item, pixmap)


class DocumentGrid(QWidget):
    files_dropped = Signal(int)
    status_message = Signal(str, object)  # (texto, cor|None)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[GridItem] = []
        self._tiles: list[_Tile] = []
        self._drag_item: GridItem | None = None
        self._thumb_cache: dict = {}
        self._bytes_loader: "Callable[[GridItem], bytes | None] | None" = None
        self._doc_exclusions: set[str] = set()
        self._building: bool = False
        self._saving: bool = False
        # Geração monotônica: cada carga incremental (drop ou set_items) captura
        # a geração atual; se outra carga começar, a anterior aborta o loop.
        self._load_gen: int = 0
        # Pool single-threaded: pdfium não é thread-safe e o lock em
        # andaime.pdf serializa as chamadas de qualquer jeito. Com 4 threads,
        # 3 ficavam bloqueadas no lock (desperdício) e tarefas antigas de um
        # processo anterior entupiam a fila do próximo.
        self._thumb_pool = QThreadPool(self)
        self._thumb_pool.setMaxThreadCount(1)
        self._thumb_signal = _ThumbnailSignal()
        self._thumb_signal.ready.connect(self._on_thumbnail_ready)
        self._setup_ui()

    def set_bytes_loader(self, loader: "Callable[[GridItem], bytes | None] | None") -> None:
        """Resolve ``arquivo_id``-only items to their BLOB on demand.

        When set, saved items need not keep their PDF bytes in RAM (G3-B):
        the thumbnail/preview is fetched lazily and streamed, never retained.
        """
        self._bytes_loader = loader

    def set_doc_exclusions(self, exclusions: set[str]) -> None:
        """Define tipos de documento excluídos do menu de classificação."""
        self._doc_exclusions = exclusions

    def set_locked(self, locked: bool) -> None:
        """Bloqueia a grade (cinza + sem interação) durante o Save assíncrono.

        ``_saving`` barra drops externos e, junto com ``_building`` (carga
        incremental), compõe o estado "ocupado" que esmaece a grade — assim ela
        não muda entre o snapshot enviado ao worker e a aplicação do resultado.
        """
        self._saving = locked
        self._apply_enabled()

    def is_locked(self) -> bool:
        """True enquanto um Save assíncrono está em andamento."""
        return self._saving

    def is_busy(self) -> bool:
        """True enquanto a grade está travada ou montando tiles incrementalmente."""
        return self._saving or self._building

    def _apply_enabled(self) -> None:
        self.setEnabled(not self.is_busy())

    def _setup_ui(self):
        self._apply_style()
        self.setAcceptDrops(True)

        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet(
            "QScrollArea { border: none; background: transparent; }"
        )
        self._scroll.viewport().setStyleSheet("background: transparent;")
        self._grid_widget = QWidget()
        self._grid_widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._grid_widget.setStyleSheet("background: transparent;")
        self._grid = QGridLayout(self._grid_widget)
        self._grid.setContentsMargins(20, 20, 20, 20)
        self._grid.setSpacing(12)
        self._grid.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
        )
        self._grid_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self._scroll.setWidget(self._grid_widget)
        layout.addWidget(self._scroll, 0, 0)

        self._empty = QLabel("Arraste arquivos aqui")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._empty.setStyleSheet(
            f"color: {colors()['text_dim']}; font-size: 14px;"
        )
        layout.addWidget(self._empty, 0, 0)
        self._empty.raise_()

        self._add_tile = _AddTile(self._open_file_picker, self)
        self._rebuild()

    def _apply_style(self):
        c = colors()
        self.setStyleSheet(
            f"DocumentGrid {{ background: {c['window_bg']}; }}"
        )
        if hasattr(self, "_add_tile"):
            self._add_tile.apply_theme()
        if hasattr(self, "_empty"):
            self._empty.setStyleSheet(
                f"color: {c['text_dim']}; font-size: 14px;"
            )

    def refresh_theme(self):
        self._apply_style()
        self._rebuild()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() or event.mimeData().hasFormat(_Tile._INTERNAL_MIME):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls() or event.mimeData().hasFormat(_Tile._INTERNAL_MIME):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if self.is_busy():
            event.ignore()
            return
        if event.mimeData().hasFormat(_Tile._INTERNAL_MIME):
            self.end_drag()
            event.acceptProposedAction()
            return
        if event.mimeData().hasUrls():
            paths = [
                u.toLocalFile() for u in event.mimeData().urls()
                if u.isLocalFile()
            ]
            if paths:
                self._add_paths(paths)
                event.acceptProposedAction()
                return
        super().dropEvent(event)

    def begin_drag(self, item: GridItem):
        self._drag_item = item
        self._apply_drag_styles()

    def end_drag(self):
        if self._drag_item is None:
            return
        self._drag_item = None
        self._apply_drag_styles()

    def drag_move_to(self, target_item: GridItem):
        if self._drag_item is None or target_item is self._drag_item:
            return
        src = self._items.index(self._drag_item)
        dst = self._items.index(target_item)
        self._move(src, dst)

    def _move(self, src: int, dst: int):
        if src == dst:
            return
        item = self._items.pop(src)
        tile = self._tiles.pop(src)
        self._items.insert(dst, item)
        self._tiles.insert(dst, tile)
        self._relayout()

    def _relayout(self):
        while self._grid.count():
            self._grid.takeAt(0)
        cols = max(1, self.width() // 152) if self.width() > 0 else 6
        for i, tile in enumerate(self._tiles):
            self._grid.addWidget(tile, i // cols, i % cols)
        idx = len(self._tiles)
        self._grid.addWidget(self._add_tile, idx // cols, idx % cols)

    def _apply_drag_styles(self):
        for tile in self._tiles:
            tile.set_ghost(
                self._drag_item is not None and tile._item is self._drag_item
            )

    def _clear_tiles(self) -> None:
        """Remove todas as tiles e esvazia o layout da grade.

        Além de tirar do layout (``takeAt``), desparenteia cada tile na hora
        (``setParent(None)``): ``deleteLater`` é diferido e, sem desparentear,
        o widget continua pintando na posição antiga até o loop de eventos
        destruí-lo — o que faz as tiles do processo anterior "persistirem".
        """
        while self._grid.count():
            self._grid.takeAt(0)
        for tile in self._tiles:
            tile.setParent(None)
            tile.deleteLater()
        self._tiles = []

    def _append_tiles_incremental(self, items: list[GridItem], gen: int) -> int:
        """Cria as tiles de ``items`` uma a uma, com a UI livre entre passos.

        Entre cada tile, ``processEvents`` mantém a janela responsiva e pinta
        os placeholders (as miniaturas chegam depois, via thread pool). Aborta
        se ``gen`` ficar obsoleto — i.e. outra carga (drop/set_items) começou.
        Retorna quantas tiles foram efetivamente adicionadas.

        A tile nova é inserida diretamente na sua célula (sem refazer todo o
        layout a cada passo — evita custo O(N²) em grades grandes); apenas o
        botão "+" é reposicionado ao final.

        Marca ``_building`` durante a construção (cobrindo tanto o drop quanto
        o ``set_items``) para esmaecer a grade e barrar edições pela metade.
        """
        self._building = True
        self._apply_enabled()
        try:
            cols = max(1, self.width() // 152) if self.width() > 0 else 6
            added = 0
            self._empty.setVisible(False)
            self._scroll.setVisible(True)
            self._grid.removeWidget(self._add_tile)
            for item in items:
                if gen != self._load_gen:
                    break
                tile = self._make_tile(item)
                # _make_tile pode ceder a UI (processEvents em callbacks); revalida
                # antes de anexar para não misturar tiles de uma carga obsoleta.
                if gen != self._load_gen:
                    tile.deleteLater()
                    break
                self._tiles.append(tile)
                pos = len(self._tiles) - 1
                self._grid.addWidget(tile, pos // cols, pos % cols)
                added += 1
                QApplication.processEvents()
            if gen == self._load_gen:
                idx = len(self._tiles)
                self._grid.addWidget(self._add_tile, idx // cols, idx % cols)
            return added
        finally:
            self._building = False
            self._apply_enabled()

    def _add_paths(self, paths: list[str]):
        """Recebe os caminhos dropados e agende a construção da grade.

        O handler de drop retorna imediatamente (``QTimer.singleShot(0)``),
        liberando a thread da UI; a decodificação (zip) e a criação das
        tiles acontecem a seguir, uma a uma, com ``processEvents`` entre
        cada uma — assim o placeholder de cada tile aparece sem travar.
        """
        if self.is_busy():
            return
        QTimer.singleShot(0, lambda: self._build_paths(paths))

    def _build_paths(self, paths: list[str]) -> None:
        from andaime.pdf import page_count

        self._load_gen += 1
        gen = self._load_gen
        before = len(self._items)
        new_items: list[GridItem] = []
        for path in paths:
            suffix = Path(path).suffix.lower()
            if suffix == ".zip":
                new_items.extend(_archive_to_items(path))
            elif suffix == ".pdf":
                n = page_count(path)
                for i in range(n):
                    new_items.append(GridItem(path=path, page=i))
            else:
                new_items.append(GridItem(path=path, page=None))
        if not new_items:
            return

        total = len(new_items)
        self.status_message.emit(
            f"Carregando {total} {'item' if total == 1 else 'itens'}…",
            "status_warning",
        )

        self._items.extend(new_items)
        self._append_tiles_incremental(new_items, gen)

        self._apply_drag_styles()
        added = len(self._items) - before
        if added:
            self.files_dropped.emit(added)
            self.status_message.emit(
                f"{added} {'item' if added == 1 else 'itens'} carregados.",
                "status_success",
            )

    def _rebuild(self):
        self._clear_tiles()
        cols = max(1, self.width() // 152) if self.width() > 0 else 6
        for i, item in enumerate(self._items):
            tile = self._make_tile(item)
            self._tiles.append(tile)
            self._grid.addWidget(tile, i // cols, i % cols)

        idx = len(self._tiles)
        self._grid.addWidget(self._add_tile, idx // cols, idx % cols)
        self._empty.setVisible(not self._items)
        self._scroll.setVisible(True)
        self._apply_drag_styles()

    def _open_file_picker(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Selecionar arquivos",
            "",
            "PDFs, Imagens e ZIP (*.pdf *.png *.jpg *.jpeg *.zip);;Todos os arquivos (*)",
        )
        if paths:
            self._add_paths(paths)

    def rotate_item(self, item: GridItem) -> bool:
        """Gira o conteúdo do item 90° (propriedade /Rotate da página PDF).

        O arquivo original em disco nunca é alterado: para itens baseados em
        ``path``/``arquivo_id`` o conteúdo rotacionado é materializado em
        ``item.data`` (o "arquivo" da aplicação). Afeta miniatura,
        pré-visualização e o PDF exportado/combinado.
        """
        from pypdf import PdfWriter

        page_no = item.page or 0
        with _source_pdf(item, self._bytes_loader) as src:
            if src is None or len(src.pages) <= page_no:
                return False
            page = src.pages[page_no]
            page.rotate(90)
            out = PdfWriter()
            out.add_page(page)
            buf = io.BytesIO()
            out.write(buf)
            item.data = buf.getvalue()
        if not item.arquivo_original and item.path:
            item.arquivo_original = Path(item.path).name
        self._invalidate_thumb(item)
        return True

    def _invalidate_thumb(self, item: GridItem) -> None:
        self._thumb_cache.pop(self._thumb_key(item), None)

    def _prune_thumb_cache(self) -> None:
        """Descarta miniaturas de itens que não estão mais na grade.

        Evita o acúmulo ilimitado no ``_thumb_cache`` ao trocar de processo
        (set_items/clear) ou ao remover uma tile (_remove_item). Chaves
        ``("mem", id)`` de itens já coletados ficam órfãs e também são
        removidas, já que seu ``id`` não casa com nenhum item vivo.
        """
        if not self._thumb_cache:
            return
        live = {self._thumb_key(it) for it in self._items}
        for key in list(self._thumb_cache):
            if key not in live:
                self._thumb_cache.pop(key, None)

    def _thumb_key(self, item: GridItem):
        aid = item.arquivo_id
        if aid is not None:
            return ("id", aid)
        path = item.path
        if path:
            return ("path", path, item.page)
        return ("mem", id(item))

    def _thumb_for(self, item: GridItem, tile: "_Tile | None" = None) -> "QPixmap | None":
        """Devolve a miniatura do item, ou ``None`` se precisar renderizar.

        - Sem ``tile``: renderiza sincronamente na thread atual (usado por
          rotação/pré-visualização, onde o conteúdo já está em RAM e é rápido).
        - Com ``tile``: se em cache, retorna; senão agenda a renderização
          assíncrona e retorna ``None`` (a tile fica vazia até o sinal).
        """
        key = self._thumb_key(item)
        cached = self._thumb_cache.get(key)
        if cached is not None and not cached.isNull():
            return cached
        if tile is None:
            pix = _thumbnail(item, self._bytes_loader)
            self._thumb_cache[key] = pix
            return pix
        self.request_thumbnail(item, tile)
        return None

    def request_thumbnail(self, item: GridItem, tile: "_Tile") -> None:
        """Enfileira a renderização da miniatura de ``item`` na thread pool."""
        # Guarda a tile alvo no próprio item para resolver a entrega: a tile
        # carrega seu pixmap apenas se ainda exibir este mesmo item.
        task = _ThumbnailTask(item, self._bytes_loader, self._thumb_signal)
        self._thumb_pool.start(task)

    def _on_thumbnail_ready(self, item: GridItem, pixmap: QPixmap) -> None:
        """Recebe a miniatura renderizada (thread principal) e a aplica."""
        key = self._thumb_key(item)
        if pixmap.isNull():
            return
        self._thumb_cache[key] = pixmap
        # Pinta nas tiles vivas que exibem este item (normalmente uma só).
        for tile in self._tiles:
            if tile._item is item:
                tile.set_pixmap(pixmap)

    def _make_tile(self, item: GridItem) -> _Tile:
        # Pixmap ``None``: a tile solicita a miniatura de forma assíncrona
        # (fora da thread da UI) e a pinta ao recebê-la — evita travar o drop.
        return _Tile(
            item, None, self,
            self._open_preview, self._remove_item, self._classify,
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._tiles or getattr(self, "_add_tile", None) is not None:
            self._relayout()

    def _open_preview(self, item: GridItem):
        start = next(
            (i for i, it in enumerate(self._items) if it is item), 0
        )
        popup = ViewerPopup(
            self._items, self, start_index=start, loader=self._bytes_loader,
            grid=self,
        )
        popup.exec()

    def _remove_item(self, item: GridItem):
        try:
            idx = self._items.index(item)
        except ValueError:
            return
        self._items.pop(idx)
        tile = self._tiles.pop(idx)
        tile.deleteLater()
        self._prune_thumb_cache()
        self._relayout()
        self._empty.setVisible(not self._items)
        self._scroll.setVisible(True)
        self._apply_drag_styles()

    def _classify(self, item: GridItem, doc_type: str) -> None:
        item.tipo_documento = doc_type
        self.sort_by_doc_type()
        self._refresh_tile_badges()

    def _refresh_tile_badges(self) -> None:
        for tile in self._tiles:
            tile._update_badge()

    def sort_by_doc_type(self) -> None:
        paired = list(zip(self._items, self._tiles))
        paired.sort(
            key=lambda p: DOC_TYPE_ORDER.get(
                p[0].tipo_documento, 99
            )
        )
        self._items = [p[0] for p in paired]
        self._tiles = [p[1] for p in paired]
        self._relayout()

    def items(self) -> list[GridItem]:
        return list(self._items)

    def set_items(self, items: list[GridItem], status_label: str | None = None) -> None:
        """Substitui o conteúdo da grade pelos ``items`` dados.

        As tiles são criadas uma a uma (com a UI livre entre passos) para não
        travar ao abrir processos com muitos arquivos. ``status_label``, se
        informado, é exibido enquanto carrega (ex.: "Carregando processo X…").
        """
        new_items = [copy.copy(it) for it in items]
        self._load_gen += 1
        gen = self._load_gen

        self._thumb_pool.clear()
        self._clear_tiles()
        self._items = new_items
        self._prune_thumb_cache()
        if not new_items:
            self._empty.setVisible(True)
            self._scroll.setVisible(True)
            self._relayout()
            self._apply_drag_styles()
            return

        if status_label:
            self.status_message.emit(status_label, "status_warning")

        self._append_tiles_incremental(new_items, gen)
        if gen == self._load_gen:
            self._apply_drag_styles()

    def clear(self) -> None:
        self._load_gen += 1
        self._thumb_pool.clear()
        self._items = []
        self._prune_thumb_cache()
        self._rebuild()



