"""UI do Sistema de Negativas - PySide6 com preview dinâmico."""

import sys
import tempfile
import webbrowser
import copy
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List

from PySide6.QtCore import Qt, QTimer
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
)
from PySide6.QtGui import QTextCursor

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "Andaime"))

from andaime.widgets import SearchableComboBox
from andaime.qt.table import (
    ColumnSpec,
    TableViewModel,
    configure_table_view,
    NoElideDelegate,
)

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
        self.table.setStyleSheet("""
            QTableView {
                background: white;
                border: 1px solid #e2e8f0;
                border-radius: 10px;
                gridline-color: #f1f5f9;
            }
            QHeaderView::section {
                background: #f8fafc;
                padding: 12px 8px;
                border: none;
                border-bottom: 2px solid #e2e8f0;
                font-weight: 700;
                font-size: 11px;
                text-transform: uppercase;
                color: #005f73;
            }
        """)

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
        scroll.setStyleSheet("QScrollArea { border: none; background: #f4f7fb; }")

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
        frame.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #005f73, stop:1 #0a9396);
                border-radius: 12px;
            }
            QLabel {
                color: white;
                font-size: 18px;
                font-weight: 600;
                text-transform: uppercase;
            }
        """)
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(20, 15, 20, 15)
        layout.addWidget(QLabel(APP_DISPLAY_NAME))
        return frame

    def _create_destinatario(self) -> QFrame:
        frame = QFrame()
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        label = QLabel("Destinatário:")
        label.setStyleSheet("font-size: 14px; font-weight: 600; color: #64748b;")
        layout.addWidget(label)

        self.destinatario_input = QLineEdit()
        self.destinatario_input.setPlaceholderText("Ex: À Autoridade Judiciária")
        self.destinatario_input.setStyleSheet("""
            QLineEdit {
                padding: 12px;
                border: 1px solid #e2e8f0;
                border-radius: 8px;
                font-size: 14px;
                background: white;
            }
        """)
        layout.addWidget(self.destinatario_input)
        return frame

    def _create_divisoes(self) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(
            "background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px;"
        )

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        checks_row = QHBoxLayout()
        checks_row.setSpacing(20)

        self.check_daf = QCheckBox("Divisão de Assistência Farmacêutica")
        self.check_daf.setStyleSheet("font-size: 14px;")

        self.check_dgmi = QCheckBox("Divisão de Gestão de Materiais e Insumos")
        self.check_dgmi.setStyleSheet("font-size: 14px;")

        checks_row.addWidget(self.check_daf)
        checks_row.addWidget(self.check_dgmi)
        checks_row.addStretch()
        layout.addLayout(checks_row)

        names_row = QHBoxLayout()
        names_row.setSpacing(10)

        self.nome_daf_input = QLineEdit()
        self.nome_daf_input.setPlaceholderText("Nome do responsável DAF")
        self.nome_daf_input.setStyleSheet("""
            QLineEdit {
                padding: 8px;
                border: 1px solid #e2e8f0;
                border-radius: 6px;
                font-size: 13px;
                background: white;
            }
        """)

        self.nome_dgmi_input = QLineEdit()
        self.nome_dgmi_input.setPlaceholderText("Nome do responsável DGMI")
        self.nome_dgmi_input.setStyleSheet("""
            QLineEdit {
                padding: 8px;
                border: 1px solid #e2e8f0;
                border-radius: 6px;
                font-size: 13px;
                background: white;
            }
        """)

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
        self.search_combo.line_edit.setStyleSheet("""
            QLineEdit {
                padding: 12px;
                border: 1px solid #e2e8f0;
                border-radius: 8px;
                font-size: 14px;
                background: white;
            }
            QLineEdit:focus {
                border: 1px solid #0a9396;
            }
        """)

        self.add_btn = QPushButton("+")
        self.add_btn.setFixedSize(50, 40)
        self.add_btn.setStyleSheet("""
            QPushButton {
                background: #0a9396;
                color: white;
                border-radius: 8px;
                font-size: 18px;
                font-weight: 600;
            }
            QPushButton:hover { background: #008b9e; }
        """)

        scl.addWidget(self.search_combo, 1)
        scl.addWidget(self.add_btn)
        layout.addWidget(search_container)

        table_label = QLabel("Itens selecionados:")
        table_label.setStyleSheet("font-size: 14px; font-weight: 600; color: #64748b;")
        layout.addWidget(table_label)

        self.table = QTableView()

        layout.addWidget(self.table)
        return frame

    def _create_botoes(self) -> QFrame:
        frame = QFrame()
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addStretch()

        self.limpar_btn = QPushButton("Limpar Tudo")
        self.limpar_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #005f73;
                padding: 12px 24px;
                border-radius: 8px;
                font-size: 14px;
                font-weight: 600;
                border: 1px solid #005f73;
            }
            QPushButton:hover { background: #f0f9ff; }
        """)

        self.imprimir_btn = QPushButton("Imprimir / Salvar PDF")
        self.imprimir_btn.setStyleSheet("""
            QPushButton {
                background: #0a9396;
                color: white;
                padding: 12px 24px;
                border-radius: 8px;
                font-size: 14px;
                font-weight: 600;
            }
            QPushButton:hover { background: #008b9e; }
        """)

        self.copiar_btn = QPushButton("Copiar Texto")
        self.copiar_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #005f73;
                padding: 12px 24px;
                border-radius: 8px;
                font-size: 14px;
                font-weight: 600;
                border: 1px solid #005f73;
            }
            QPushButton:hover { background: #f0f9ff; }
        """)

        layout.addWidget(self.imprimir_btn)
        layout.addWidget(self.copiar_btn)
        layout.addWidget(self.limpar_btn)
        return frame

    def _create_resultado(self) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet("""
            QFrame {
                background: white;
                border: 1px dashed #005f73;
                border-radius: 10px;
            }
        """)

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
        self.resultado_text.setStyleSheet("""
            QTextEdit {
                background: white;
                border: none;
                font-size: 14px;
                line-height: 1.6;
            }
        """)
        self.resultado_text.document().contentsChanged.connect(
            self._atualizar_altura_resultado
        )

        layout.addWidget(self.resultado_text)
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

            remover_btn = QPushButton("×")
            remover_btn.setFixedSize(30, 30)
            remover_btn.setStyleSheet("""
                QPushButton {
                    background: #fee2e2;
                    color: #dc2626;
                    border-radius: 4px;
                    font-size: 18px;
                    font-weight: 600;
                }
                QPushButton:hover { background: #fecaca; }
            """)
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

    # ──────────────────────────── CONFIG ────────────────────────────

    def _load_config(self):
        theme = self.config.get("theme", "light")
        self._apply_theme(theme)

        # Carrega nomes salvos
        nome_daf = self.config.get("nome_daf", "")
        nome_dgmi = self.config.get("nome_dgmi", "")

        if nome_daf:
            self.nome_daf_input.setText(nome_daf)
        if nome_dgmi:
            self.nome_dgmi_input.setText(nome_dgmi)

    def _save_nomes_config(self):
        """Salva os nomes das divisões no config."""
        nome_daf = self.nome_daf_input.text().strip()
        nome_dgmi = self.nome_dgmi_input.text().strip()

        self.config.set("nome_daf", nome_daf)
        self.config.set("nome_dgmi", nome_dgmi)

    def _apply_theme(self, theme: str):
        if theme == "dark":
            self.setStyleSheet("""
                QMainWindow { background: #1e293b; }
                QLabel { color: #e2e8f0; }
                QTextEdit { background: #0f172a; color: #e2e8f0; }
                QTableView { background: #1e293b; color: #e2e8f0; }
                QHeaderView::section { background: #334155; color: #e2e8f0; }
            """)
        else:
            self.setStyleSheet("")

    def closeEvent(self, event):
        """Cleanup resources when window closes."""
        self._save_nomes_config()
        self.itens_selecionados.clear()
        self._debounce_timer.stop()
        if self._last_temp_path and Path(self._last_temp_path).exists():
            Path(self._last_temp_path).unlink(missing_ok=True)
        event.accept()
