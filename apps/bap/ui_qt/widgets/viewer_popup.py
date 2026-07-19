from __future__ import annotations

from typing import Callable
from pathlib import Path
from contextlib import contextmanager

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
)

from src.ui_qt.styles import colors, context_menu_stylesheet
from src.constants import DOC_TYPE_LABELS
from src.models import GridItem


def _build_classify_menu(parent, *, current: str, exclusions: set[str],
                         on_classify: "Callable[[str], None]") -> QMenu:
    """Constrói o menu de classificação de tipo de documento.

    Lista ``DOC_TYPE_LABELS`` (exceto ``exclusions``), marca o tipo atual
    como selecionado e chama ``on_classify`` com a chave escolhida.
    Compartilhado entre a tile da grade e o visualizador (preview).
    """
    menu = QMenu(parent)
    menu.setStyleSheet(context_menu_stylesheet())
    for key, label in DOC_TYPE_LABELS.items():
        if key in exclusions:
            continue
        action = menu.addAction(label)
        action.setCheckable(True)
        action.setChecked(key == current)
        action.triggered.connect(
            lambda checked=False, k=key: on_classify(k)
        )
    return menu


@contextmanager
def _resolve_item_page(
    item: GridItem,
    loader: "Callable[[GridItem], bytes | None] | None" = None,
    scale: float = 2.0,
):
    """Resolve um item em ``(qimage, image_path)`` para renderização.

    Para PDFs, renderiza a página via ``andaime.pdf``. Para imagens em disco,
    devolve o caminho para carga direta via ``QImage(path)``.
    """
    page_no = item.page or 0

    if (
        item.data is None
        and item.path is not None
        and Path(item.path).suffix.lower() != ".pdf"
    ):
        yield None, item.path
        return

    raw = item.raw_bytes(loader)
    if not raw:
        yield None, None
        return

    from andaime.pdf import render_page

    yield render_page(raw, page_no, scale), None


class _PanLabel(QLabel):
    def __init__(self, scroll, parent=None):
        super().__init__(parent)
        self._scroll = scroll
        self._panning = False
        self._last = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._panning = True
            self._last = event.globalPosition().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._panning and self._last is not None:
            pos = event.globalPosition().toPoint()
            delta = pos - self._last
            self._last = pos
            h = self._scroll.horizontalScrollBar()
            v = self._scroll.verticalScrollBar()
            h.setValue(h.value() - delta.x())
            v.setValue(v.value() - delta.y())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._panning = False
        self.setCursor(Qt.CursorShape.ArrowCursor)
        super().mouseReleaseEvent(event)


class ViewerPopup(QDialog):
    """Visualizador em tela cheia que navega por todos os documentos da grade.

    Cada item da grade é uma página/documento; o contador e as setas
    avançam/retrocedem entre os itens (não dentro de um único PDF, já que
    cada arquivo é uma página única no modelo de armazenamento atual).
    """

    def __init__(self, items, parent=None, start_index: int = 0, loader: "Callable[[GridItem], bytes | None] | None" = None, grid: "object | None" = None):
        super().__init__(parent)
        self._items = list(items) if items else []
        self._index = max(0, min(start_index, len(self._items) - 1))
        self._img: QImage | None = None
        self._loader = loader
        self._grid = grid
        self._user_zoom = 1.0

        self.setWindowTitle("Documento")
        self._setup_ui()
        self._render_index(self._index)
        self.showFullScreen()

    def contextMenuEvent(self, event):
        if self._grid is None or not self._items:
            return
        current = self._items[self._index].tipo_documento
        menu = _build_classify_menu(
            self,
            current=current,
            exclusions=self._grid._doc_exclusions,
            on_classify=self._classify_current,
        )
        menu.exec(event.globalPos())

    def _classify_current(self, doc_type: str) -> None:
        if self._grid is None or not self._items:
            return
        item = self._items[self._index]
        self._grid._classify(item, doc_type)
        self._update_type_label()

    def _setup_ui(self):
        c = colors()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        bar = QHBoxLayout()
        bar.setContentsMargins(12, 8, 12, 8)
        bar.setSpacing(8)

        self._prev_btn = QPushButton("<")
        self._prev_btn.setFixedSize(36, 30)
        self._prev_btn.clicked.connect(self._prev)
        self._next_btn = QPushButton(">")
        self._next_btn.setFixedSize(36, 30)
        self._next_btn.clicked.connect(self._next)
        self._page_label = QLabel("")
        self._page_label.setStyleSheet(
            f"color: {c['text_dim']}; font-size: 13px;"
        )
        self._page_label.setMinimumWidth(90)
        self._page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._type_label = QLabel("")
        self._type_label.setStyleSheet(
            f"color: {c['text_dim']}; font-size: 13px;"
        )
        self._type_label.setMinimumWidth(120)
        self._type_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        bar.addWidget(self._prev_btn)
        bar.addWidget(self._page_label)
        bar.addWidget(self._next_btn)
        bar.addStretch(1)
        bar.addWidget(self._type_label)
        bar.addStretch(1)

        zoom_out = QPushButton("\u2212")
        zoom_out.setFixedSize(36, 30)
        zoom_out.clicked.connect(self._zoom_out)
        zoom_in = QPushButton("+")
        zoom_in.setFixedSize(36, 30)
        zoom_in.clicked.connect(self._zoom_in)
        self._zoom_label = QLabel("100%")
        self._zoom_label.setStyleSheet(
            f"color: {c['text_dim']}; font-size: 13px;"
        )
        self._zoom_label.setMinimumWidth(52)
        self._zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        fit_btn = QPushButton("Ajustar")
        fit_btn.setFixedHeight(30)
        fit_btn.clicked.connect(self._zoom_fit)

        bar.addWidget(zoom_out)
        bar.addWidget(self._zoom_label)
        bar.addWidget(zoom_in)
        bar.addWidget(fit_btn)
        bar.addStretch(1)

        close_btn = QPushButton("Fechar")
        close_btn.setFixedHeight(30)
        close_btn.clicked.connect(self.reject)
        bar.addWidget(close_btn)
        layout.addLayout(bar)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(False)
        self._scroll.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter
        )
        self._image_label = _PanLabel(self._scroll)
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._scroll.setWidget(self._image_label)
        layout.addWidget(self._scroll)

        QShortcut(QKeySequence(Qt.Key.Key_Left), self, self._prev)
        QShortcut(QKeySequence(Qt.Key.Key_Right), self, self._next)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, self.reject)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if event.angleDelta().y() > 0:
                self._zoom_in()
            else:
                self._zoom_out()
            event.accept()
        else:
            super().wheelEvent(event)

    def _image_for(self, item: GridItem) -> QImage | None:
        with _resolve_item_page(item, self._loader) as (qimage, image_path):
            if qimage is not None:
                return qimage
            if image_path is not None:
                img = QImage(image_path)
                return None if img.isNull() else img
            return None

    def _render_index(self, index: int):
        if not self._items:
            self._page_label.setText("0 / 0")
            self._prev_btn.setEnabled(False)
            self._next_btn.setEnabled(False)
            return
        self._index = max(0, min(index, len(self._items) - 1))
        item = self._items[self._index]

        self._img = self._image_for(item)
        self._apply_pixmap()

        total = len(self._items)
        self._page_label.setText(f"{self._index + 1} / {total}")
        self._prev_btn.setEnabled(self._index > 0)
        self._next_btn.setEnabled(self._index < total - 1)

        title = item.display_name
        self.setWindowTitle(title)
        self._update_type_label()

    def _apply_pixmap(self):
        if self._img is None or self._img.isNull():
            self._image_label.clear()
            return
        vp = self._scroll.viewport()
        fit_w = max(50, vp.width() - 8) / self._img.width()
        fit_h = max(50, vp.height() - 8) / self._img.height()
        fit = min(fit_w, fit_h)
        if fit <= 0:
            fit = 1.0
        scale = fit * self._user_zoom
        pixmap = QPixmap.fromImage(self._img).scaled(
            int(self._img.width() * scale),
            int(self._img.height() * scale),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._image_label.setPixmap(pixmap)
        self._image_label.adjustSize()

    def _zoom_in(self):
        self._user_zoom = min(self._user_zoom * 1.2, 8.0)
        self._apply_pixmap()
        self._update_zoom_label()

    def _zoom_out(self):
        self._user_zoom = max(self._user_zoom / 1.2, 0.2)
        self._apply_pixmap()
        self._update_zoom_label()

    def _zoom_fit(self):
        self._user_zoom = 1.0
        self._apply_pixmap()
        self._update_zoom_label()

    def _update_zoom_label(self):
        self._zoom_label.setText(f"{int(round(self._user_zoom * 100))}%")

    def _update_type_label(self):
        if not self._items:
            self._type_label.setText("")
            return
        doc_type = self._items[self._index].tipo_documento
        label = DOC_TYPE_LABELS.get(doc_type, "Sem classificação")
        self._type_label.setText(f"Tipo: {label}")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_pixmap()

    def _prev(self):
        self._render_index(self._index - 1)

    def _next(self):
        self._render_index(self._index + 1)
