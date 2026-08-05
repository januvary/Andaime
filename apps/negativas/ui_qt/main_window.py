"""UI do Sistema de Negativas - PySide6 com preview dinâmico."""

import sys
import tempfile
import webbrowser
import copy
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List

from PySide6.QtCore import Qt, QTimer, QDate, QBuffer, QIODevice, QUrl
from PySide6.QtGui import QTextCursor, QImage, QPixmap, QTextDocument, QPainter
from PySide6.QtSvgWidgets import QSvgRenderer
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QCheckBox,
    QTextEdit,
    QFrame,
    QScrollArea,
    QTableView,
    QHeaderView,
    QMessageBox,
    QSizePolicy,
    QDateEdit,
)

from andaime.widgets import SearchableComboBox
from andaime.qt.table import (
    ColumnSpec,
    TableViewModel,
    configure_table_view,
    NoElideDelegate,
)
from negativas.ui_qt.theme import (
    get_stylesheet,
    qpalette,
    make_button,
    get_palette,
    set_theme,
    get_theme,
    ThemeToggleButton,
    colors,
)
from negativas.utils import svg_base64, clear_svg_cache

from negativas.database.negativas_database import NegativasDatabase
from negativas.config import NegativasConfig
from negativas.models import ItemSelecionado, NegativaData
from negativas.constants import (
    APP_DISPLAY_NAME,
    BRASAO_SVG_PATH,
    DEBOUNCE_MS,
    BRASAO_HEIGHT,
)
from negativas.services.document_builder import DocumentBuilder


class MainWindow(QMainWindow):
    def __init__(self, app_instance):
        super().__init__()
        self.app = app_instance
        self.db = app_instance.db
        self.config = app_instance.config
        self.document_builder = DocumentBuilder(self.db)

        self.itens_selecionados: List[ItemSelecionado] = []
        self._item_names: set[str] = set()
        self.next_item_id = 0
        self.selected_medicamento = None
        self._last_preview_data: NegativaData | None = None
        self._scroll_area: QScrollArea | None = None
        self._last_temp_path: str | None = None
        self._styled_widgets: list = []  # Track widgets that need theme updates

        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.timeout.connect(self._atualizar_preview)

        self._setup_ui()
        self._setup_table_model()
        self._setup_signals()

        # Find scroll area after UI is built
        self._scroll_area = self.findChild(QScrollArea)

        self._load_config()
        self._atualizar_preview()

    def _setup_table_model(self):
        """Configura o modelo da tabela de itens selecionados."""
        columns = [
            ColumnSpec(
                header="Nome",
                getter=lambda item: item.nome,
                alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                resize_mode=QHeaderView.ResizeMode.Stretch,
            ),
            ColumnSpec(
                header="Fornecimento",
                getter=lambda item: self._get_categoria_label(item.categoria),
                alignment=Qt.AlignmentFlag.AlignCenter,
                resize_mode=QHeaderView.ResizeMode.ResizeToContents,
            ),
            ColumnSpec(
                header="Opções",
                getter=lambda item: "",
                resize_mode=QHeaderView.ResizeMode.Fixed,
                width=200,
            ),
            ColumnSpec(
                header="",
                getter=lambda item: "",
                resize_mode=QHeaderView.ResizeMode.Fixed,
                width=40,
            ),
        ]

        self.table_model = TableViewModel(columns, id_getter=lambda item: item.id)
        self.table.setModel(self.table_model)
        self.table.setItemDelegate(NoElideDelegate())
        configure_table_view(self.table, columns)

        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(45)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def _get_categoria_label(self, categoria: str) -> str:
        """Retorna o label amigável da categoria."""
        return {
            "NAO_PADRONIZADO": "Não Padronizado",
            "CEAF": "CEAF",
            "USAFA": "USAFA",
            "CAPS II": "CAPS II",
        }.get(categoria, "")

    # ──────────────────────────── UI SETUP ────────────────────────────

    def _setup_ui(self):
        self.setWindowTitle(APP_DISPLAY_NAME)
        self.resize(1300, 800)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setObjectName("mainScroll")

        main_container = QWidget()
        main_container.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        main_layout = QVBoxLayout(main_container)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(20)

        two_columns = QWidget()
        two_columns_layout = QHBoxLayout(two_columns)
        two_columns_layout.setContentsMargins(0, 0, 0, 0)
        two_columns_layout.setSpacing(20)

        # ── Coluna esquerda ──
        left_column = QWidget()
        left_column.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        left_layout = QVBoxLayout(left_column)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(20)

        left_layout.addWidget(self._create_header())
        left_layout.addWidget(self._create_destinatario())
        left_layout.addWidget(self._create_divisoes())
        left_layout.addWidget(self._create_search_and_items())
        left_layout.addWidget(self._create_botoes())
        left_layout.addStretch()

        # ── Coluna direita ──
        right_column = QWidget()
        right_column.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        right_layout = QVBoxLayout(right_column)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(20)

        right_layout.addWidget(self._create_resultado())
        right_layout.addStretch()

        two_columns_layout.addWidget(left_column, 1)
        two_columns_layout.addWidget(right_column, 1)
        main_layout.addWidget(two_columns)
        main_layout.addSpacing(20)

        scroll.setWidget(main_container)

        final_layout = QVBoxLayout(central_widget)
        final_layout.setContentsMargins(0, 0, 0, 0)
        final_layout.setSpacing(0)
        final_layout.addWidget(scroll)

    def _create_header(self) -> QFrame:
        frame = QFrame()
        frame.setProperty("class", "panel")
        frame.setObjectName("header_frame")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(20, 15, 20, 15)
        layout.addWidget(QLabel(APP_DISPLAY_NAME))
        layout.addStretch()

        # Theme toggle button
        self.theme_toggle = ThemeToggleButton()
        self.theme_toggle.theme_toggled.connect(self._on_theme_toggled)
        layout.addWidget(self.theme_toggle)

        self._update_header_style()
        self._styled_widgets.append(("header", frame))
        return frame

    def _create_destinatario(self) -> QFrame:
        frame = QFrame()
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        label = QLabel("Destinatário:")
        label.setProperty("heading", "section")
        layout.addWidget(label)

        self.destinatario_input = QLineEdit()
        self.destinatario_input.setPlaceholderText("Ex: À Autoridade Judiciária")
        layout.addWidget(self.destinatario_input)
        return frame

    def _create_divisoes(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("divisoes_frame")

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        checks_row = QHBoxLayout()
        checks_row.setSpacing(20)

        self.check_daf = QCheckBox("Divisão de Assistência Farmacêutica")

        self.check_dgmi = QCheckBox("Divisão de Gestão de Materiais e Insumos")

        checks_row.addWidget(self.check_daf)
        checks_row.addWidget(self.check_dgmi)
        checks_row.addStretch()
        layout.addLayout(checks_row)

        names_row = QHBoxLayout()
        names_row.setSpacing(10)

        self.nome_daf_input = QLineEdit()
        self.nome_daf_input.setPlaceholderText("Nome do responsável DAF")

        self.nome_dgmi_input = QLineEdit()
        self.nome_dgmi_input.setPlaceholderText("Nome do responsável DGMI")

        self.nome_daf_container = QWidget()
        QHBoxLayout(self.nome_daf_container).addWidget(self.nome_daf_input)

        self.nome_dgmi_container = QWidget()
        QHBoxLayout(self.nome_dgmi_container).addWidget(self.nome_dgmi_input)

        names_row.addWidget(self.nome_daf_container)
        names_row.addWidget(self.nome_dgmi_container)
        layout.addLayout(names_row)

        self.nome_dgmi_container.setVisible(False)

        self.check_daf.toggled.connect(self.nome_daf_container.setVisible)
        self.check_dgmi.toggled.connect(self.nome_dgmi_container.setVisible)

        self._update_divisoes_frame_style()
        self._styled_widgets.append(("divisoes", frame))
        return frame

    def _create_search_and_items(self) -> QFrame:
        frame = QFrame()
        frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        search_label = QLabel("Buscar medicamento:")
        search_label.setStyleSheet("font-size: 14px; font-weight: 600; color: #64748b;")
        layout.addWidget(search_label)

        search_container = QWidget()
        scl = QHBoxLayout(search_container)
        scl.setContentsMargins(0, 0, 0, 0)
        scl.setSpacing(10)

        self.search_combo = SearchableComboBox(
            self._search_medicamentos,
            placeholder="Digite o nome do medicamento...",
        )

        self.add_btn = make_button("+", role="primary")
        self.add_btn.setFixedSize(50, 40)
        self.add_btn.setProperty("class", "primary")

        scl.addWidget(self.search_combo, 1)
        scl.addWidget(self.add_btn)
        layout.addWidget(search_container)

        table_label = QLabel("Itens selecionados:")
        table_label.setProperty("heading", "section")
        layout.addWidget(table_label)

        self.table = QTableView()

        layout.addWidget(self.table)
        return frame

    def _create_botoes(self) -> QFrame:
        frame = QFrame()
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.data_edit = QDateEdit()
        self.data_edit.setDisplayFormat("dd/MM/yyyy")
        self.data_edit.setDate(QDate.currentDate())
        self.data_edit.setCalendarPopup(True)
        layout.addWidget(self.data_edit)

        layout.addStretch()

        self.limpar_btn = make_button("Limpar Tudo", role="flat")
        self.imprimir_btn = make_button("Imprimir / Salvar PDF", role="primary")
        self.copiar_btn = make_button("Copiar Texto", role="flat")

        layout.addWidget(self.imprimir_btn)
        layout.addWidget(self.copiar_btn)
        layout.addWidget(self.limpar_btn)
        return frame

    def _create_resultado(self) -> QFrame:
        frame = QFrame()
        frame.setProperty("class", "box")
        frame.setObjectName("result_frame")

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(25, 25, 25, 25)
        layout.setSpacing(25)

        self.resultado_text = QTextEdit()
        self.resultado_text.setReadOnly(True)
        self.resultado_text.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.resultado_text.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.resultado_text.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.resultado_text.document().contentsChanged.connect(
            self._atualizar_altura_resultado
        )

        layout.addWidget(self.resultado_text)

        self._update_result_frame_style()
        self._styled_widgets.append(("result", frame))
        return frame

    # ──────────────────────────── SIGNALS ────────────────────────────

    def _setup_signals(self):
        self.add_btn.clicked.connect(self._adicionar_item)
        self.limpar_btn.clicked.connect(self._limpar_tudo)
        self.imprimir_btn.clicked.connect(self._imprimir_documento)
        self.copiar_btn.clicked.connect(self._copiar_texto)

        self.search_combo.selection_changed.connect(self._on_medicamento_selecionado)

        # Checkbox toggles → immediate update
        self.check_daf.toggled.connect(self._atualizar_preview_imediato)
        self.check_dgmi.toggled.connect(self._atualizar_preview_imediato)

        # Text fields → debounced update
        self.destinatario_input.textChanged.connect(self._debounce_preview)
        self.nome_daf_input.textChanged.connect(self._debounce_preview)
        self.nome_dgmi_input.textChanged.connect(self._debounce_preview)

        # Initialize checkbox states after connecting signals
        self.check_daf.setChecked(True)
        self.check_dgmi.setChecked(False)

    # ──────────────────────────── SEARCH / ITEMS ────────────────────────────

    def _search_medicamentos(self, query: str) -> Dict[str, str]:
        medicamentos = self.db.buscar_medicamentos(query)
        return {str(m.id): f"{m.nome} ({m.categoria})" for m in medicamentos}

    def _on_medicamento_selecionado(self, medicamento_id: Optional[str]):
        if medicamento_id:
            medicamento = self.db.get_medicamento_por_id(int(medicamento_id))
            if medicamento:
                self.selected_medicamento = medicamento

    def _adicionar_item(self):
        if self.selected_medicamento:
            medicamento = self.selected_medicamento
            if medicamento.nome in self._item_names:
                QMessageBox.warning(
                    self, "Duplicata", "Este medicamento já foi adicionado."
                )
                self.selected_medicamento = None
                return

            self.next_item_id += 1
            self.itens_selecionados.append(
                ItemSelecionado(
                    id=self.next_item_id,
                    nome=medicamento.nome,
                    categoria=medicamento.categoria,
                    em_falta=not medicamento.disponivel,
                    is_medicamento=True,
                )
            )
            self._item_names.add(medicamento.nome)
            self._atualizar_tabela()
            self.selected_medicamento = None
            self.search_combo.clear()
        else:
            texto = self.search_combo.current_text().strip()
            if not texto:
                return

            if texto in self._item_names:
                QMessageBox.warning(self, "Duplicata", "Este item já foi adicionado.")
                return

            self.next_item_id += 1
            self.itens_selecionados.append(
                ItemSelecionado(
                    id=self.next_item_id,
                    nome=texto,
                    categoria="NAO_PADRONIZADO",
                    em_falta=False,
                    is_medicamento=True,
                )
            )
            self._item_names.add(texto)
            self._atualizar_tabela()
            self.search_combo.clear()

    def _atualizar_tabela(self):
        """Atualiza a tabela com os itens selecionados."""
        self.table_model.set_rows(list(self.itens_selecionados))

        # Recria widgets para as colunas de opções e remover
        for row, item in enumerate(self.itens_selecionados):
            opcoes_widget = QWidget()
            ol = QHBoxLayout(opcoes_widget)
            ol.setContentsMargins(5, 5, 5, 5)
            ol.setSpacing(10)

            if item.categoria in ["USAFA", "CAPS II"]:
                cb = QCheckBox("Em falta")
                row_idx = row  # Capture for closure
                cb.stateChanged.connect(
                    lambda state, r=row_idx: self._on_falta_changed(
                        r, state == Qt.CheckState.Checked.value
                    )
                )
                cb.setChecked(item.em_falta)
                ol.addWidget(cb)
            elif item.categoria == "NAO_PADRONIZADO":
                cb = QCheckBox("Medicamento")
                row_idx = row  # Capture for closure
                cb.stateChanged.connect(
                    lambda state, r=row_idx: self._on_tipo_changed(
                        r, state == Qt.CheckState.Checked.value
                    )
                )
                cb.setChecked(item.is_medicamento)
                ol.addWidget(cb)

            ol.addStretch()
            self.table.setIndexWidget(self.table_model.index(row, 2), opcoes_widget)

            remover_btn = make_button("×", role="icon")
            remover_btn.setFixedSize(30, 30)
            remover_btn.setObjectName(f"remove_btn_{row}")
            self._update_remove_button_style(remover_btn)
            remover_btn.clicked.connect(lambda _, r=row: self._remover_item(r))
            self.table.setIndexWidget(self.table_model.index(row, 3), remover_btn)

        self._atualizar_altura_tabela()
        self._atualizar_preview_imediato()

    def _atualizar_altura_tabela(self):
        header_h = self.table.horizontalHeader().height()
        rows = self.table_model.rowCount()
        if rows == 0:
            height = header_h + 45 + 4
        else:
            height = header_h + (rows * 45) + 4
        if self.table.minimumHeight() == height:
            return
        self.table.setMinimumHeight(height)
        self.table.setMaximumHeight(height)

    def _atualizar_altura_resultado(self):
        doc = self.resultado_text.document()
        doc.setTextWidth(self.resultado_text.viewport().width())
        height = int(doc.size().height()) + 20
        new_height = max(50, height)
        if self.resultado_text.minimumHeight() == new_height:
            return
        self.resultado_text.setMinimumHeight(new_height)
        self.resultado_text.setMaximumHeight(new_height)

    def _on_falta_changed(self, row: int, em_falta: bool):
        if row < len(self.itens_selecionados):
            self.itens_selecionados[row].em_falta = em_falta
            self._atualizar_preview_imediato()

    def _on_tipo_changed(self, row: int, is_medicamento: bool):
        if row < len(self.itens_selecionados):
            self.itens_selecionados[row].is_medicamento = is_medicamento
            self._atualizar_preview_imediato()

    def _remover_item(self, row: int):
        if 0 <= row < len(self.itens_selecionados):
            nome = self.itens_selecionados[row].nome
            self._item_names.discard(nome)
            del self.itens_selecionados[row]
            self._atualizar_tabela()

    # ──────────────────────────── PREVIEW ────────────────────────────

    def _debounce_preview(self):
        self._debounce_timer.start(DEBOUNCE_MS)

    def _atualizar_preview_imediato(self):
        self._debounce_timer.stop()
        self._atualizar_preview()

    def _atualizar_preview(self):
        """Lê o estado do formulário, gera HTML e atualiza o preview preservando o scroll."""
        data = self._coletar_dados()
        if data == self._last_preview_data:
            return
        self._last_preview_data = data

        html = self.document_builder.build_html(data)
        self._atualizar_preview_com_svg(html)

    def _coletar_dados(self) -> NegativaData:
        """Lê todos os campos do formulário e retorna um snapshot."""
        return NegativaData(
            destinatario=self.destinatario_input.text().strip()
            or "autoridade competente",
            usos_daf=self.check_daf.isChecked(),
            usos_dgmi=self.check_dgmi.isChecked(),
            nome_daf=self.nome_daf_input.text().strip(),
            nome_dgmi=self.nome_dgmi_input.text().strip(),
            data_hoje=self.data_edit.text().strip(),
            itens=[copy.deepcopy(item) for item in self.itens_selecionados],
        )

    # ──────────────────────────── ACTIONS ────────────────────────────

    def _limpar_tudo(self):
        self.itens_selecionados.clear()
        self._item_names.clear()
        self.next_item_id = 0
        self.destinatario_input.clear()
        self.nome_daf_input.clear()
        self.nome_dgmi_input.clear()
        self.data_edit.setDate(QDate.currentDate())
        self.check_daf.setChecked(True)
        self.check_dgmi.setChecked(False)
        self._atualizar_tabela()
        self._atualizar_preview_imediato()

    def _imprimir_documento(self):
        if not self.itens_selecionados:
            QMessageBox.warning(self, "Aviso", "Adicione pelo menos um item.")
            return

        if not self.check_daf.isChecked() and not self.check_dgmi.isChecked():
            QMessageBox.warning(self, "Aviso", "Selecione pelo menos uma divisão.")
            return

        if self.check_daf.isChecked() and not self.nome_daf_input.text().strip():
            QMessageBox.warning(self, "Aviso", "Informe o nome do responsável da DAF.")
            return

        if self.check_dgmi.isChecked() and not self.nome_dgmi_input.text().strip():
            QMessageBox.warning(self, "Aviso", "Informe o nome do responsável da DGMI.")
            return

        html_content = self.document_builder.build_html(self._coletar_dados())

        if self._last_temp_path and Path(self._last_temp_path).exists():
            Path(self._last_temp_path).unlink(missing_ok=True)

        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".html", delete=False
        ) as f:
            f.write(html_content)
            self._last_temp_path = f.name

        webbrowser.open(f"file://{self._last_temp_path}")

    def _copiar_texto(self):
        clipboard = QApplication.clipboard()
        clipboard.setText(self.resultado_text.toPlainText())
        QMessageBox.information(
            self, "Sucesso", "Texto copiado para a área de transferência!"
        )

    def _on_theme_toggled(self, dark_mode: bool):
        """Handle theme toggle from the header button."""
        theme = "dark" if dark_mode else "light"
        set_theme(theme)
        palette = get_palette(dark_mode)

        qapp = QApplication.instance()
        if isinstance(qapp, QApplication):
            qapp.setPalette(qpalette(palette))
            qapp.setStyleSheet(get_stylesheet(theme))

        self.config.set("theme", theme)
        self._update_theme_dependent_styles()
        
        # Clear SVG cache to regenerate with new theme color
        clear_svg_cache()

        # Clear preview cache to force regeneration with new theme colors
        self._last_preview_data = None
        # Delay preview update slightly to avoid height calculation issues
        QTimer.singleShot(10, self._atualizar_preview_imediato)

    def _update_header_style(self):
        """Update header frame styling based on current theme."""
        c = colors()
        header_frame = self.findChild(QFrame, "header_frame")
        if header_frame:
            header_frame.setStyleSheet(f"""
                QFrame {{
                    background: {c["btn_primary"]};
                    border-radius: 12px;
                }}
                QLabel {{
                    color: {c["text"]};
                    font-size: 18px;
                    font-weight: 600;
                    text-transform: uppercase;
                }}
            """)

    def _update_result_frame_style(self):
        """Update result frame styling based on current theme."""
        c = colors()
        result_frame = self.findChild(QFrame, "result_frame")
        if result_frame:
            result_frame.setStyleSheet(f"""
                QFrame {{
                    background: {c["input_bg"]};
                    border: 1px dashed {c["panel_border"]};
                    border-radius: 10px;
                }}
            """)

    def _update_divisoes_frame_style(self):
        """Update divisões frame styling based on current theme."""
        c = colors()
        divisoes_frame = self.findChild(QFrame, "divisoes_frame")
        if divisoes_frame:
            divisoes_frame.setStyleSheet(f"""
                QFrame {{
                    background: {c["panel_bg"]};
                    border: 1px solid {c["panel_border"]};
                    border-radius: 10px;
                }}
            """)

    def _update_remove_button_style(self, button):
        """Update remove button styling based on current theme."""
        c = colors()
        button.setStyleSheet(f"""
            QPushButton {{
                background: {c["status_error"]};
                color: {c["box_bg"]};
                border-radius: 4px;
                font-size: 18px;
                font-weight: 600;
            }}
            QPushButton:hover {{ background: {c["status_error"]}; }}
        """)

    def _update_theme_dependent_styles(self):
        """Update all widgets that have theme-dependent inline styles."""
        self._update_header_style()
        self._update_result_frame_style()
        self._update_divisoes_frame_style()

        # Update remove buttons in table
        for row in range(self.table_model.rowCount()):
            remove_btn = self.table.indexWidget(self.table_model.index(row, 3))
            if remove_btn and isinstance(remove_btn, QPushButton):
                self._update_remove_button_style(remove_btn)

    # ──────────────────────────── CONFIG ────────────────────────────

    def _load_config(self):
        # Load theme preference and sync toggle button
        theme = self.config.get("theme", "dark")
        set_theme(theme)

        # Sync theme toggle button state
        if hasattr(self, 'theme_toggle'):
            is_dark = get_theme() == "dark"
            self.theme_toggle._dark = is_dark
            self.theme_toggle._update_icon()

        # Clear SVG cache to ensure it uses correct theme color
        clear_svg_cache()
        
        # Update theme-dependent styles
        self._update_theme_dependent_styles()

        # Clear preview cache to ensure theme colors are applied on initial load
        self._last_preview_data = None

        # Carrega nomes salvos
        nome_daf = self.config.get("nome_daf", "")
        nome_dgmi = self.config.get("nome_dgmi", "")
        data_hoje = self.config.get("data_hoje", "")

        if nome_daf:
            self.nome_daf_input.setText(nome_daf)
        if nome_dgmi:
            self.nome_dgmi_input.setText(nome_dgmi)
        if data_hoje:
            try:
                from datetime import datetime
                dt = datetime.strptime(data_hoje, "%d/%m/%Y")
                self.data_edit.setDate(QDate(dt.year, dt.month, dt.day))
            except ValueError:
                pass

    def _render_svg_pixmap(self, width: int, height: int) -> QPixmap:
        """Renderiza o SVG como QPixmap com a cor do tema."""
        import base64

        svg_data = svg_base64()
        if not svg_data:
            return QPixmap()

        svg_bytes = base64.b64decode(svg_data)
        svg_renderer = QSvgRenderer(svg_bytes)

        pixmap = QPixmap(width, height)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        svg_renderer.render(painter)
        painter.end()

        return pixmap

    def _atualizar_preview_com_svg(self, html: str):
        """Atualiza o preview adicionando o SVG como recurso Qt."""
        scroll_area = self._scroll_area
        scroll_pos = scroll_area.verticalScrollBar().value() if scroll_area else 0

        # Render SVG as QPixmap
        pixmap = self._render_svg_pixmap(200, BRASAO_HEIGHT * 2)
        if pixmap.isNull():
            self.resultado_text.setHtml(html)
            self._atualizar_altura_resultado()
            if scroll_area:
                scroll_area.verticalScrollBar().setValue(scroll_pos)
            return

        # Replace data URI with resource URL
        html_com_svg = html.replace(
            'src="data:image/svg+xml;base64,' + svg_base64() + '"',
            'src="brasao://brasao"'
        )

        # Set HTML first
        self.resultado_text.setHtml(html_com_svg)

        # Add image resource to document
        doc = self.resultado_text.document()
        resource_url = QUrl("brasao://brasao")
        doc.addResource(QTextDocument.ResourceType.ImageResource, resource_url, pixmap)

        self._atualizar_altura_resultado()

        if scroll_area:
            scroll_area.verticalScrollBar().setValue(scroll_pos)

    def _save_nomes_config(self):
        """Salva os nomes das divisões no config."""
        nome_daf = self.nome_daf_input.text().strip()
        nome_dgmi = self.nome_dgmi_input.text().strip()
        data_hoje = self.data_edit.text().strip()

        self.config.set("nome_daf", nome_daf)
        self.config.set("nome_dgmi", nome_dgmi)
        self.config.set("data_hoje", data_hoje)

    def closeEvent(self, event):
        """Cleanup resources when window closes."""
        self._save_nomes_config()
        self.itens_selecionados.clear()
        self._debounce_timer.stop()
        if self._last_temp_path and Path(self._last_temp_path).exists():
            Path(self._last_temp_path).unlink(missing_ok=True)
        event.accept()
