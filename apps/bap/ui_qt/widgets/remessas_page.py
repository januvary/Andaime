"""Página de Remessas (SS-54).

Espelha a ``PreviewPage`` do RAC: a área principal é um ``QTabWidget``
com duas abas (Renovação / Solicitação), cada uma com uma busca e uma
tabela de processos (um processo por linha).

A página **não** possui barra superior nem seletor de status — apenas a
barra inferior própria (RemessaLabel à esquerda, "Retornar" no centro,
"Enviar Remessa" à direita).
"""

from __future__ import annotations

from datetime import date

from bap.utils.date_utils import format_date_display

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QApplication,
    QDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QFrame,
    QTableView,
    QTreeWidget,
    QTreeWidgetItem,
    QTabWidget,
    QTextEdit,
    QHeaderView,
    QVBoxLayout,
    QWidget,
    QHBoxLayout,
)

from bap.ui_qt.styles import colors, context_menu_stylesheet
from bap.ui_qt.widgets.remessa import RemessaLabel
from bap.constants import (
    STATUS_LABELS,
    STATUS_SEMANTIC,
    SOLICITACAO_LABELS,
    TIPO_UPPER,
    Status,
)
from bap.utils.remessa_email import ensure_processo_pdf
from bap.utils.arquivo_storage import resolve_arquivos_root
from bap.utils.text_utils import format_phone
from bap.ui_qt.widgets.dialogs import (
    open_input_dialog,
    scaffold_dialog,
    make_dialog_button_row,
    pick_from_list,
    confirm_dialog,
)
from bap.ui_qt.widgets.status_label import show_status_dialog
from andaime.qt import StatusLine
from andaime.qt.bottom_bar import BottomBar
from andaime.qt.table import (
    ColumnSpec,
    NoElideDelegate,
    TableViewModel,
    configure_table_view,
)
from andaime.widgets import SearchableComboBox, static_search_fn
from andaime.dates import parse_date

# Abas: Renovação / Solicitação (campo ``solicitacao`` do processo).
_TAB_KEYS = ["primeira", "renovacao"]


def _status_color(status: str) -> QColor:
    hex_color = colors().get(
        STATUS_SEMANTIC.get(status, "text_dim"), "#6B7280"
    )
    return QColor(hex_color)


def _format_obs(p) -> str:
    if not p.last_obs:
        return ""
    date_str = (
        format_date_display(p.last_obs_at[:10]) if p.last_obs_at else ""
    )
    sep = f"{date_str} — " if date_str else ""
    return f"{sep}{p.last_obs}"


_LEFT = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
_CENTER = Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter

_REMESSA_COLUMNS = [
    ColumnSpec(
        "Paciente",
        lambda p: p.paciente_nome or "",
        alignment=_LEFT,
        header_alignment=_LEFT,
        resize_mode=QHeaderView.ResizeMode.ResizeToContents,
        padding=5,
    ),
    ColumnSpec(
        "Tipo",
        lambda p: TIPO_UPPER.get(p.tipo, (p.tipo or "").upper()),
        resize_mode=QHeaderView.ResizeMode.ResizeToContents,
        padding=5,
    ),
    ColumnSpec(
        "Descrição",
        lambda p: p.descricao or "",
        resize_mode=QHeaderView.ResizeMode.Fixed,
        width=160,
    ),
    ColumnSpec(
        "Observação",
        _format_obs,
        alignment=_LEFT,
        header_alignment=_LEFT,
        resize_mode=QHeaderView.ResizeMode.Stretch,
    ),
    ColumnSpec(
        "Status",
        lambda p: STATUS_LABELS.get(p.status, p.status or "—").upper(),
        foreground=lambda p: _status_color(p.status),
        resize_mode=QHeaderView.ResizeMode.ResizeToContents,
        padding=5,
    ),
    ColumnSpec(
        "Telefone",
        lambda p: format_phone(p.paciente_telefone) or "",
        resize_mode=QHeaderView.ResizeMode.ResizeToContents,
        padding=5,
    ),
]

# Opções de recategorização (submenu "Editar → Tipo"): valores das duas
# dimensões (solicitação + tipo) que o processo pode assumir.
_SOLICITACAO_OPTIONS = [(k, SOLICITACAO_LABELS[k]) for k in _TAB_KEYS]
_TIPO_OPTIONS = [
    ("medicamento", "Medicamento"),
    ("nutricao", "Nutrição"),
    ("bomba", "Bomba"),
]


def _tabs_style() -> str:
    c = colors()
    return f"""
        QTabWidget::pane {{
            background: {c['panel_header_bg']};
            border: none;
            border-top: 1px solid {c['panel_border']};
        }}
        QTabBar {{
            background: transparent;
        }}
        QTabBar::tab {{
            background: {c['panel_bg']};
            color: {c['text_dim']};
            padding: 6px 16px;
            border: 1px solid {c['panel_border']};
            border-bottom: none;
            border-top-left-radius: 6px;
            border-top-right-radius: 6px;
            margin-right: 2px;
        }}
        QTabBar::tab:selected {{
            background: {c['panel_header_bg']};
            color: {c['text']};
            font-weight: 600;
            border-color: {c['btn_primary']};
            border-bottom: none;
        }}
        QTabBar::tab:!selected:hover {{
            background: {c['bg_hover']};
            color: {c['text_secondary']};
        }}
    """


class RemessasPage(QWidget):
    """Página de remessas: tabela de processos por aba (renov/solic)."""

    retornar = Signal()
    novo_processo = Signal()
    enviar = Signal()
    remessa_changed = Signal(object)  # Lote | None
    ver_processo = Signal(int)  # processo_id

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(0)

        self._db = None
        self._config = None
        # Runner assíncrono (DbAsyncRunner) injetado pela MainWindow. Quando
        # ausente (ex.: testes), ``refresh`` cai no caminho síncrono.
        self._runner = None
        # Assinatura (lote_id, mostrar_incompletos) do último ``_populate``
        # bem-sucedido, usada para pular repopulação em navegação (item C).
        self._last_signature = None
        # Token monotônico para descartar resultados de fetches obsoletos.
        self._refresh_token = 0

        self._content = QWidget(self)
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(10, 8, 10, 8)
        self._content_layout.setSpacing(8)

        # Busca navegacional (nome ou telefone) acima das abas/tabela.
        self._search = SearchableComboBox(
            search_fn=static_search_fn({}),
            placeholder="Buscar por nome ou telefone...",
        )
        self._search.selection_changed.connect(self._on_search_select)
        search_wrap = QWidget()
        search_wrap_lay = QVBoxLayout(search_wrap)
        search_wrap_lay.setContentsMargins(12, 12, 12, 0)
        search_wrap_lay.setSpacing(0)
        search_wrap_lay.addWidget(self._search)
        self._content_layout.addWidget(search_wrap)

        self._status_line = StatusLine(self)
        self._content_layout.addWidget(self._status_line)

        self._show_incompletos = QCheckBox("Mostrar incompletos")
        self._show_incompletos.setChecked(True)
        self._show_incompletos.toggled.connect(lambda _checked: self.refresh())

        self.remessa_label = RemessaLabel(self)
        self.remessa_label.remessa_changed.connect(self.remessa_changed.emit)
        self.remessa_label.remessa_changed.connect(self.refresh)

        from andaime.qt.theme import make_button

        self._enviar_btn = make_button("Enviar Remessa", "primary")
        self._enviar_btn.clicked.connect(self.enviar.emit)
        self._enviar_btn.setEnabled(False)

        self._atualizacoes_btn = make_button("Atualizações", "flat-fill")
        self._atualizacoes_btn.setMaximumWidth(160)
        self._atualizacoes_btn.clicked.connect(self._show_atulizacoes)

        self._bottom_bar = BottomBar(
            parent=self,
            left_widget=self.remessa_label,
            status_widget=self._atualizacoes_btn,
            actions=[("Novo Processo", "flat-fill", self.novo_processo.emit)],
            right_widget=self._enviar_btn,
            col_weights=(2, 4, 4, 4),
        )

        # Painel único (padrão Emissor): conteúdo + rodapé dentro de um
        # QFrame "panel" com borda e cantos arredondados.
        panel = QFrame()
        panel.setProperty("class", "panel")
        panel_lay = QVBoxLayout(panel)
        panel_lay.setContentsMargins(0, 0, 0, 0)
        panel_lay.setSpacing(0)
        panel_lay.addWidget(self._content, stretch=1)
        panel_lay.addWidget(self._bottom_bar, stretch=0)

        layout.addWidget(panel, stretch=1)

        self._build_tabs()

    # ========== Construção ==========

    def _build_tabs(self) -> None:
        old = self.findChild(QTabWidget)
        if old is not None:
            self._content_layout.removeWidget(old)
            old.setParent(None)
            old.deleteLater()

        self._tabs = QTabWidget()
        self._tabs.setMinimumHeight(400)
        self._tabs.setStyleSheet(_tabs_style())
        self._tabs.currentChanged.connect(lambda _i: None)

        corner = QWidget()
        corner_layout = QHBoxLayout(corner)
        corner_layout.setContentsMargins(0, 0, 6, 9)
        corner_layout.addWidget(self._show_incompletos)
        self._tabs.setCornerWidget(corner, Qt.Corner.TopRightCorner)

        self._content_layout.addWidget(self._tabs, stretch=1)

        self._tables: dict[str, QTableView] = {}
        self._models: dict[str, TableViewModel] = {}

        for key in _TAB_KEYS:
            tab, tab_layout = self._make_tab(key)
            self._tabs.addTab(tab, SOLICITACAO_LABELS[key])

        self.refresh()

    # ========== Linha de status ==========

    def set_status(
        self,
        text: str,
        color: str | None = None,
        path: str | None = None,
    ) -> None:
        self._status_line.set_status(text, color, path)

    def _make_tab(self, key: str):
        tab = QWidget()
        tab_layout = QVBoxLayout(tab)
        tab_layout.setContentsMargins(12, 0, 12, 12)
        tab_layout.setSpacing(8)

        table = QTableView()
        model = TableViewModel(_REMESSA_COLUMNS)
        table.setModel(model)
        configure_table_view(table, _REMESSA_COLUMNS)

        table.setAlternatingRowColors(True)
        table.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        table.verticalHeader().setVisible(False)
        table.setShowGrid(False)
        table.setTextElideMode(Qt.TextElideMode.ElideNone)
        table.setItemDelegate(NoElideDelegate())
        table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        table.customContextMenuRequested.connect(
            lambda pos, t=table: self._show_row_menu(t, pos)
        )
        table.doubleClicked.connect(
            lambda idx, t=table: self._on_row_double_clicked(t, idx.row())
        )
        copy_sc = QShortcut(QKeySequence.StandardKey.Copy, table)
        copy_sc.setContext(Qt.ShortcutContext.WidgetShortcut)
        copy_sc.activated.connect(lambda t=table: self._copy_current_cell(t))

        tab_layout.addWidget(table, stretch=1)
        self._tables[key] = table
        self._models[key] = model

        return tab, tab_layout

    def _set_loading(self, visible: bool) -> None:
        if visible:
            self.set_status("Carregando…", "status_warning")
        else:
            self.set_status("")

    # ========== Dados ==========

    def set_remessa_db(self, db) -> None:
        self._db = db
        self.remessa_label.set_db(db)
        self._search.set_search_fn(self._search_processos)

    def set_config(self, config) -> None:
        self._config = config

    def set_async_runner(self, runner) -> None:
        """Injeta o ``DbAsyncRunner`` para que ``refresh`` busque os processos
        fora da thread principal. Sem ele, ``refresh`` roda síncrono."""
        self._runner = runner

    def set_remessa_active(self, lote, emit: bool = True) -> None:
        self.remessa_label.set_active(lote, emit=emit)
        self._update_enviar_button(lote)

    def remessa_active(self):
        return self.remessa_label.active()

    def focus_search(self) -> None:
        """Foca o campo de busca de processos (atalho Ctrl+R)."""
        self._search.focus_search()

    def _update_enviar_button(self, lote=None) -> None:
        if lote is None:
            lote = self.remessa_active()
        today = date.today().isoformat()
        is_today = lote is not None and lote.date == today
        self._enviar_btn.setEnabled(is_today)

    def refresh(self, force: bool = True) -> None:
        """Recarrega as tabelas de processos.

        A busca (JOIN de 4 tabelas) roda no ``DbAsyncRunner`` quando
        disponível; as linhas são construídas no callback (thread principal).
        Sem runner, cai no caminho síncrono.

        ``force=False`` (usado na navegação) pula a repopulação quando a
        assinatura ``(lote_id, mostrar_incompletos)`` não mudou desde o
        último ``_populate`` — evita reconstruir tabelas idênticas.
        """
        if self._db is None:
            return
        lote = self.remessa_active()
        self._update_enviar_button(lote)
        if lote is None:
            for key in _TAB_KEYS:
                self._clear_table(key)
                self._update_tab_label(key, 0)
            self._last_signature = None
            return

        show_incompletos = self._show_incompletos.isChecked()
        signature = (lote.id, show_incompletos)
        if not force and signature == self._last_signature:
            return

        # Limpa as tabelas imediatamente ao trocar de remessa, para que o
        # usuário veja o feedback de carregamento em vez das linhas antigas.
        for key in _TAB_KEYS:
            self._clear_table(key)
            self._update_tab_label(key, 0)
        self._last_signature = None

        # Invalida qualquer fetch em andamento e cria um token para este.
        self._refresh_token += 1
        token = self._refresh_token
        lote_id = lote.id

        def _fetch():
            processos = self._db.get_processos_by_lote(lote_id)
            if not show_incompletos:
                processos = [p for p in processos if p.status != Status.INCOMPLETO]
            return processos

        def _apply(processos) -> None:
            # Descarta resultados obsoletos (outro refresh foi disparado).
            if token != self._refresh_token:
                return
            for key in _TAB_KEYS:
                self._populate(key, [p for p in processos if p.solicitacao == key])
            self._last_signature = signature
            self._set_loading(False)

        if self._runner is not None:
            self._set_loading(True)
            self._runner.run(_fetch, on_done=_apply)
        else:
            _apply(_fetch())


    # ========== Busca navegacional ==========

    def _search_processos(self, query: str) -> dict[str, str]:
        """Busca por nome ou telefone em todas as remessas.

        Retorna ``{processo_id: "DD/MM/AAAA - NOME"}`` com a remessa ativa
        priorizada no topo dos resultados.
        """
        if self._db is None or not query.strip():
            return {}
        active = self.remessa_active()
        active_id = active.id if active else None
        resultados = self._db.search_processos(
            query=query, active_lote_id=active_id, limit=20
        )
        return {
            str(p.id): f"{format_date_display(p.lote_date or '')} - {p.paciente_nome or ''}"
            for p in resultados
        }

    def _on_search_select(self, data) -> None:
        if not data or self._db is None:
            return
        try:
            processo_id = int(data)
        except (ValueError, TypeError):
            return
        processo = self._db.get_processo_by_id(processo_id)
        if processo is None:
            return

        # A busca retorna processos "incompleto" mesmo quando o filtro em
        # massa ("Mostrar incompletos") está desmarcado. Ao selecionar um
        # explicitamente, revela-os para que a navegação até ele funcione
        # (caso contrário a linha não existe na tabela e a seleção anterior
        # permanece).
        if processo.status == Status.INCOMPLETO and not self._show_incompletos.isChecked():
            self._show_incompletos.setChecked(True)

        # Troca a remessa ativa se o processo pertence a outra remessa.
        active = self.remessa_active()
        if processo.lote_id is not None and (
            active is None or active.id != processo.lote_id
        ):
            lote = self._db.get_lote_by_id(processo.lote_id)
            if lote is not None:
                self.set_remessa_active(lote, emit=True)  # dispara refresh

        # Troca para a aba correspondente (solicitação/renovação).
        if processo.solicitacao in _TAB_KEYS:
            self._tabs.setCurrentIndex(_TAB_KEYS.index(processo.solicitacao))

        self._highlight_processo(processo.solicitacao, processo_id)
        self._search.clear()

    def _highlight_processo(self, tab_key: str, processo_id: int) -> None:
        table = self._tables.get(tab_key)
        model = self._models.get(tab_key)
        if table is None or model is None:
            return
        row = model.find_row_by_id(processo_id)
        if row is not None:
            table.selectRow(row)
            table.scrollTo(
                model.index(row, 0), QTableView.ScrollHint.PositionAtCenter
            )
            table.setFocus()

    def refresh_theme(self) -> None:
        """Reaplica o estilo das abas ao trocar o tema."""
        self._tabs.setStyleSheet(_tabs_style())

    def _clear_table(self, key: str) -> None:
        model = self._models.get(key)
        if model is not None:
            model.set_rows([])

    def _populate(self, key: str, processos) -> None:
        model = self._models.get(key)
        if model is None:
            return

        processos = sorted(
            processos,
            key=lambda p: (
                0 if p.status == Status.COMPLETO else 1,
                (p.paciente_nome or "").lower(),
            ),
        )
        model.set_rows(processos)
        self._update_tab_label(key, len(processos))

    def _update_tab_label(self, key: str, count: int) -> None:
        idx = _TAB_KEYS.index(key)
        self._tabs.setTabText(idx, f"{SOLICITACAO_LABELS[key]} ({count})")

    def _show_row_menu(self, table: QTableView, pos) -> None:
        row = table.rowAt(pos.y())
        if row < 0:
            return
        model = table.model()
        processo_id = model.data(model.index(row, 0), Qt.ItemDataRole.UserRole)
        if processo_id is None or self._db is None:
            return
        table.selectRow(row)

        menu = QMenu(self)
        menu.setStyleSheet(context_menu_stylesheet())

        processo = self._db.get_processo_by_id(processo_id)

        col = table.columnAt(pos.x())
        if col in (0, 5):
            cell_text = model.data(model.index(row, col), Qt.ItemDataRole.DisplayRole)
            if cell_text:
                copy_action = menu.addAction("Copiar")
                copy_action.triggered.connect(
                    lambda _c=False, txt=cell_text: self._copy_text(txt)
                )
                menu.addSeparator()

        status_action = menu.addAction("Status")
        status_action.triggered.connect(
            lambda _c=False, pid=processo_id: self._edit_status(pid)
        )
        ver_action = menu.addAction("Ver processo")
        ver_action.triggered.connect(
            lambda _c=False, pid=processo_id: self.ver_processo.emit(pid)
        )

        gerar_pdf_action = menu.addAction("Gerar PDF")
        gerar_pdf_action.triggered.connect(
            lambda _c=False, pid=processo_id: self._gerar_pdf(pid)
        )

        edit_menu = menu.addMenu("Editar")

        obs_action = edit_menu.addAction("Observações")
        obs_action.triggered.connect(
            lambda _c=False, pid=processo_id: self._show_status_log(pid)
        )
        desc_action = edit_menu.addAction("Descrição")
        desc_action.triggered.connect(
            lambda _c=False, pid=processo_id: self._edit_field(
                pid, "descricao", "Descrição"
            )
        )

        tipo_menu = edit_menu.addMenu("Tipo")
        cur_solic = processo.solicitacao if processo else None
        cur_tipo = processo.tipo if processo else None
        for key, label in _SOLICITACAO_OPTIONS:
            if key == cur_solic:
                continue
            act = tipo_menu.addAction(label)
            act.triggered.connect(
                lambda _c=False, pid=processo_id, k=key: self._change_solicitacao(
                    pid, k
                )
            )
        for key, label in _TIPO_OPTIONS:
            if key == cur_tipo:
                continue
            act = tipo_menu.addAction(label)
            act.triggered.connect(
                lambda _c=False, pid=processo_id, k=key: self._change_tipo(pid, k)
            )

        nome_action = edit_menu.addAction("Nome do paciente")
        nome_action.triggered.connect(
            lambda _c=False, pid=processo_id: self._edit_paciente_nome(pid)
        )

        remessa_action = edit_menu.addAction("Remessa")
        remessa_action.triggered.connect(
            lambda _c=False, pid=processo_id: self._edit_remessa(pid)
        )

        edit_menu.addSeparator()
        del_action = edit_menu.addAction("Excluir processo")
        del_action.triggered.connect(
            lambda _c=False, pid=processo_id: self._delete_processo(pid)
        )

        menu.exec(table.viewport().mapToGlobal(pos))

    def _on_row_double_clicked(self, table: QTableView, row: int) -> None:
        if row < 0:
            return
        model = table.model()
        processo_id = model.data(model.index(row, 0), Qt.ItemDataRole.UserRole)
        if processo_id is not None:
            self.ver_processo.emit(processo_id)

    def _copy_current_cell(self, table: QTableView) -> None:
        """Copia o texto da célula atual (apenas nome e telefone)."""
        index = table.currentIndex()
        if not index.isValid() or index.column() not in (0, 5):
            return
        text = index.data(Qt.ItemDataRole.DisplayRole)
        if text:
            QApplication.clipboard().setText(text)

    def _copy_text(self, text: str) -> None:
        if text:
            QApplication.clipboard().setText(text)

    def _edit_field(self, processo_id: int, field: str, title: str) -> None:
        if self._db is None:
            return
        processo = self._db.get_processo_by_id(processo_id)
        if processo is None:
            return
        current = getattr(processo, field) or ""
        text = open_input_dialog(
            self,
            title,
            placeholder=f"{title}...",
            initial=current,
            confirm_label="Salvar",
            multiline=(field == "observacoes"),
        )
        if text is not None:
            self._db.update_processo(processo_id, **{field: text})
            self.refresh()

    def _edit_status(self, processo_id: int) -> None:
        if self._db is None:
            return
        processo = self._db.get_processo_by_id(processo_id)
        if processo is None:
            return
        show_status_dialog(
            self.window(),
            processo.status,
            lambda key, obs: self._change_status(processo_id, key, obs),
            on_observation=lambda obs: self._add_observation(processo_id, obs),
        )

    def _gerar_pdf(self, processo_id: int) -> None:
        if self._db is None:
            return
        processo = self._db.get_processo_by_id(processo_id)
        if processo is None:
            return
        pdf_path, has_docs = ensure_processo_pdf(
            self._db, resolve_arquivos_root(self._config), processo
        )
        if not has_docs or pdf_path is None:
            self.set_status("Processo sem documentos para gerar PDF.")
            return
        from andaime.qt import relative_path

        status_path = relative_path(resolve_arquivos_root(self._config), pdf_path)
        self.set_status(
            f"PDF gerado: {status_path}", "status_success", path=pdf_path
        )

    def _show_status_log(self, processo_id: int) -> None:
        if self._db is None:
            return
        dlg, layout = scaffold_dialog(self, "Histórico de Status", min_width=440)
        dlg.setMinimumHeight(360)

        list_widget = QListWidget()
        list_widget.setWordWrap(True)
        list_widget.setAlternatingRowColors(True)
        list_widget.setProperty("class", "remessa-tree")
        list_widget.itemDoubleClicked.connect(
            lambda item: self._edit_log_obs(item, processo_id, dlg)
        )
        self._populate_status_log(list_widget, processo_id)

        layout.addWidget(list_widget, stretch=1)

        btn_row, [close] = make_dialog_button_row([("Fechar", "primary")])
        close.clicked.connect(dlg.accept)
        layout.addLayout(btn_row)
        dlg.exec()

    def _populate_status_log(
        self, list_widget: QListWidget, processo_id: int
    ) -> None:
        list_widget.clear()
        logs = self._db.get_status_logs(processo_id)
        for log in logs:
            date_str = (
                format_date_display(log["created_at"][:10])
                if log["created_at"]
                else ""
            )
            old = STATUS_LABELS.get(log["old_status"], log["old_status"] or "—")
            new = STATUS_LABELS.get(log["new_status"], log["new_status"] or "—")
            label = f"{date_str}  {old} → {new}"
            obs = (log["observacoes"] or "").strip()
            if obs:
                label += f"\n{obs}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, log["id"])
            item.setForeground(_status_color(log["new_status"]))
            list_widget.addItem(item)

        if not logs:
            list_widget.addItem(QListWidgetItem("Nenhum registro de status."))

    def _edit_log_obs(
        self, item: QListWidgetItem, processo_id: int, dlg: QDialog
    ) -> None:
        log_id = item.data(Qt.ItemDataRole.UserRole)
        if log_id is None:
            return
        logs = self._db.get_status_logs(processo_id)
        current = next(
            (lg["observacoes"] or "" for lg in logs if lg["id"] == log_id), ""
        )
        text = open_input_dialog(
            dlg,
            "Observação",
            placeholder="Observação...",
            initial=current,
            confirm_label="Salvar",
            multiline=True,
        )
        if text is not None:
            self._db.update_status_log(log_id, text)
            self._populate_status_log(
                dlg.findChild(QListWidget), processo_id
            )
            self.refresh()

    def _change_status(
        self, processo_id: int, key: str, observacoes: str = ""
    ) -> None:
        if self._db is None:
            return
        self._db.update_processo_status(processo_id, key, observacoes or None)
        self.refresh()

    def _add_observation(self, processo_id: int, observacoes: str) -> None:
        if self._db is None:
            return
        self._db.add_status_observation(processo_id, observacoes)
        self.refresh()

    def _change_tipo(self, processo_id: int, key: str) -> None:
        if self._db is None:
            return
        self._db.update_processo(processo_id, tipo=key)
        self.refresh()

    def _change_solicitacao(self, processo_id: int, key: str) -> None:
        if self._db is None:
            return
        self._db.update_processo(processo_id, solicitacao=key)
        self.refresh()

    def _edit_remessa(self, processo_id: int) -> None:
        if self._db is None:
            return
        processo = self._db.get_processo_by_id(processo_id)
        if processo is None:
            return
        lote = self._select_lote_dialog(processo.lote_id)
        if lote is None:
            return
        self._db.reassign_processo_lote(processo_id, lote.id)
        self.refresh()

    def _select_lote_dialog(self, current_lote_id: object) -> object | None:
        lotes = self._db.get_all_lotes()
        lotes = sorted(
            lotes,
            key=lambda item: (parse_date(item.date) or date.today()),
            reverse=True,
        )

        def _fmt(lote):
            text = format_date_display(lote.date)
            if lote.id == current_lote_id:
                text += "  (atual)"
            return text, lote

        return pick_from_list(
            self,
            "Mover para Remessa",
            lotes,
            _fmt,
            hint="Selecione a remessa de destino:",
            confirm_label="Mover",
            max_height=320,
        )

    def _delete_processo(self, processo_id: int) -> None:
        if self._db is None:
            return
        processo = self._db.get_processo_by_id(processo_id)
        if processo is None:
            return
        nome = processo.paciente_nome or "processo"
        if not self._confirm_delete(nome):
            return
        self._db.delete_processo(processo_id)
        self.refresh()

    def _confirm_delete(self, nome: str) -> bool:
        return confirm_dialog(
            self,
            "Excluir processo",
            f"Excluir o processo de <b>{nome}</b>? Esta ação não pode ser desfeita.",
            confirm_label="Excluir",
            danger=True,
        )

    # ========== Atualizações DRS ==========

    def update_atulizacoes_count(self) -> None:
        if self._db is None:
            return
        count = self._db.get_unseen_drs_count()
        if count > 0:
            self._atualizacoes_btn.setText(f"Atualizações ({count})")
        else:
            self._atualizacoes_btn.setText("Atualizações")

    def _show_atulizacoes(self) -> None:
        if self._db is None:
            return
        messages = self._db.get_drs_messages()
        if not messages:
            return

        dlg, layout = scaffold_dialog(
            self, "Atualizações DRS", spacing=8, min_width=520
        )
        dlg.setMinimumHeight(500)

        tree = QTreeWidget()
        tree.setHeaderLabels(["Data", "Status"])
        tree.setProperty("class", "remessa-tree")
        tree.setAlternatingRowColors(True)
        tree.header().setStretchLastSection(False)
        tree.header().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        tree.header().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )

        by_patient: dict[int, dict] = {}
        for msg in messages:
            pid = msg["paciente_id"]
            if pid not in by_patient:
                by_patient[pid] = {"nome": msg["paciente_nome"], "msgs": []}
            by_patient[pid]["msgs"].append(msg)

        for pdata in by_patient.values():
            pdata["msgs"].sort(
                key=lambda m: m.get("message_date") or "", reverse=True
            )
        sorted_patients = sorted(
            by_patient.values(),
            key=lambda p: p["msgs"][0].get("message_date") or "",
            reverse=True,
        )

        for pdata in sorted_patients:
            header = QTreeWidgetItem(
                [pdata["nome"], f"({len(pdata['msgs'])})"]
            )
            header.setFlags(header.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            tree.addTopLevelItem(header)
            has_unseen = any(not msg.get("seen") for msg in pdata["msgs"])
            header.setExpanded(has_unseen)

            for msg in pdata["msgs"]:
                date_str = format_date_display(
                    (msg.get("message_date") or "")[:10]
                )
                status_key = msg.get("inferred_status") or ""
                status_label = STATUS_LABELS.get(status_key, "—")
                child = QTreeWidgetItem([date_str, status_label])
                child.setData(0, Qt.ItemDataRole.UserRole, msg)

                if not msg.get("seen"):
                    f = child.font(0)
                    f.setBold(True)
                    child.setFont(0, f)

                child.setForeground(1, _status_color(status_key))
                header.addChild(child)

        tree.itemClicked.connect(self._on_atulizacoes_click)
        layout.addWidget(tree)

        btn_row, [close_btn] = make_dialog_button_row(
            [("Fechar", "primary")]
        )
        close_btn.clicked.connect(dlg.accept)
        layout.addLayout(btn_row)

        dlg.exec()
        self.update_atulizacoes_count()

    def _on_atulizacoes_click(self, item: QTreeWidgetItem, _col: int) -> None:
        msg = item.data(0, Qt.ItemDataRole.UserRole)
        if msg is None:
            return
        parent_dlg = item.treeWidget().window()
        self._open_email_content(msg, parent_dlg)
        font = item.font(0)
        font.setBold(False)
        item.setFont(0, font)

    def _open_email_content(self, msg: dict, parent=None) -> None:
        if self._db is None:
            return
        self._db.mark_drs_message_seen(msg["message_id"])

        dlg, layout = scaffold_dialog(
            parent or self, "E-mail DRS", spacing=8, min_width=520
        )
        dlg.setMinimumHeight(480)

        meta_parts = []
        if msg.get("from_email"):
            meta_parts.append(f"De: {msg['from_email']}")
        if msg.get("subject"):
            meta_parts.append(f"Assunto: {msg['subject']}")
        date_str = format_date_display((msg.get("message_date") or "")[:10])
        if date_str:
            meta_parts.append(f"Data: {date_str}")
        meta = QLabel("\n".join(meta_parts))
        meta.setWordWrap(True)
        meta.setStyleSheet("color: #6B7280; font-size: 12px;")
        layout.addWidget(meta)

        body_edit = QTextEdit()
        body_edit.setReadOnly(True)
        body_edit.setPlainText(msg.get("body") or msg.get("snippet") or "")
        layout.addWidget(body_edit, stretch=1)

        btn_row, [fechar, alterar] = make_dialog_button_row(
            [("Fechar", "flat-fill"), ("Alterar Status", "primary")]
        )
        fechar.clicked.connect(dlg.reject)
        alterar.clicked.connect(dlg.accept)
        layout.addLayout(btn_row)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._alterar_status(
                msg["paciente_id"], msg.get("inferred_status") or ""
            )

    def _alterar_status(self, paciente_id: int, inferred_status: str = "") -> None:
        if self._db is None:
            return
        processos = self._db.get_processos_by_paciente(paciente_id)
        if not processos:
            return

        latest_date = processos[0].lote_date or ""
        latest = [p for p in processos if (p.lote_date or "") == latest_date]

        if len(latest) == 1:
            processo = latest[0]
        else:
            processo = self._select_process_dialog(latest)

        if processo is None:
            return

        def on_select(key, obs=""):
            self._db.update_processo_status(processo.id, key, obs or None)
            self.refresh()

        def on_observation(obs):
            self._db.add_status_observation(processo.id, obs)
            self.refresh()

        show_status_dialog(
            self.window(),
            processo.status,
            on_select,
            on_observation=on_observation,
            preselect=inferred_status or None,
        )

    def _select_process_dialog(self, processos: list) -> object | None:
        def _fmt(p):
            date_str = format_date_display(p.lote_date or "")
            sol = SOLICITACAO_LABELS.get(p.solicitacao, p.solicitacao)
            tipo = TIPO_UPPER.get(p.tipo, (p.tipo or "").upper())
            return f"{date_str}  —  {sol}  —  {tipo}", p.id

        pid = pick_from_list(
            self,
            "Selecionar Processo",
            processos,
            _fmt,
            hint="Múltiplos processos nesta remessa — selecione um:",
            confirm_label="Selecionar",
            max_height=160,
        )
        if pid is None:
            return None
        return self._db.get_processo_by_id(pid)
