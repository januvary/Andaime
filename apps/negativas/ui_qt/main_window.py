"""UI do Sistema de Negativas - PySide6 com preview dinâmico."""

import sys
import webbrowser
import copy
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List

from PySide6.QtCore import Qt, QTimer, QDate

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

from andaime.qt.widgets import SearchableComboBox
from andaime.qt.status_line import StatusLine
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


from negativas.database.negativas_database import NegativasDatabase
from negativas.config import NegativasConfig
from negativas.models import ItemSelecionado, NegativaData
from negativas.constants import (
    APP_DISPLAY_NAME,
    DEBOUNCE_MS,
)
from negativas.services.document_builder import DocumentBuilder


class MainWindow(QMainWindow):
    def __init__(self, app_instance):
        super().__init__()
        self.app = app_instance
        self.db = app_instance.db
        self.config = app_instance.config
        self.document_builder = DocumentBuilder(self.db)

        from andaime.db_worker import DatabaseWorker
        from andaime.qt.db_runner import DbAsyncRunner

        self._db_worker = DatabaseWorker(self.db)
        self._db_runner = DbAsyncRunner(self._db_worker)

        self.itens_selecionados: List[ItemSelecionado] = []
        self._item_names: set[str] = set()
        self.next_item_id = 0
        self.selected_medicamento = None
        self._last_preview_data: NegativaData | None = None
        self._scroll_area: QScrollArea | None = None
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
        self._status_line = StatusLine()
        left_layout.addWidget(self._status_line)
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
        self.imprimir_btn = make_button("Salvar PDF", role="primary")
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

            # Wrap in container to center the button vertically in the cell
            remove_container = QWidget()
            rc_layout = QHBoxLayout(remove_container)
            rc_layout.setContentsMargins(5, 0, 5, 0)
            rc_layout.setSpacing(0)
            rc_layout.addStretch()
            rc_layout.addWidget(remover_btn)
            rc_layout.addStretch()
            self.table.setIndexWidget(self.table_model.index(row, 3), remove_container)

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

        html = self.document_builder.build_html(data, include_brasao=False)

        scroll_area = self._scroll_area
        scroll_pos = scroll_area.verticalScrollBar().value() if scroll_area else 0
        self.resultado_text.setHtml(html)
        self._atualizar_altura_resultado()
        if scroll_area:
            scroll_area.verticalScrollBar().setValue(scroll_pos)

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
        self._status_line.set_status("")

    def _imprimir_documento(self):
        if not self.itens_selecionados:
            self._status_line.set_status("Adicione pelo menos um item.", "status_warning")
            return

        if not self.check_daf.isChecked() and not self.check_dgmi.isChecked():
            self._status_line.set_status("Selecione pelo menos uma divisão.", "status_warning")
            return

        if self.check_daf.isChecked() and not self.nome_daf_input.text().strip():
            self._status_line.set_status("Informe o nome do responsável da DAF.", "status_warning")
            return

        if self.check_dgmi.isChecked() and not self.nome_dgmi_input.text().strip():
            self._status_line.set_status("Informe o nome do responsável da DGMI.", "status_warning")
            return

        from negativas.pdf.negativa_pdf import NegativaPDF

        data = self._coletar_dados()
        safe_dest = data.destinatario.replace(" ", "_")
        safe_date = data.data_hoje.replace("/", "-")
        filename = f"Negativa_{safe_dest}_{safe_date}.pdf"

        from andaime.paths import get_root_directory
        save_dir = get_root_directory() / "PARA ASSINAR"
        save_dir.mkdir(parents=True, exist_ok=True)
        path = str(save_dir / filename)

        self._status_line.set_status("Gerando PDF...", "status_warning")

        def _work():
            pdf_gen = NegativaPDF(self.db)
            pdf_gen.generate(data, output_path=path)
            return path

        self._db_runner.run(
            _work,
            on_done=lambda p: (
                self._status_line.set_status(f"PDF salvo — {p}", "status_success", path=p),
                webbrowser.open(f"file://{p}"),
            ),
            on_error=lambda e: self._status_line.set_status(f"Erro ao gerar PDF: {e}", "status_error"),
        )

    def _copiar_texto(self):
        clipboard = QApplication.clipboard()
        clipboard.setText(self.resultado_text.toPlainText())
        self._status_line.set_status("Texto copiado para a área de transferência!", "status_success")

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
            container = self.table.indexWidget(self.table_model.index(row, 3))
            if container:
                remove_btn = container.findChild(QPushButton)
                if remove_btn:
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
        worker = getattr(self, "_db_worker", None)
        if worker is not None:
            try:
                worker.shutdown(wait=True)
            except Exception:
                pass
        event.accept()
