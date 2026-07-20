#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Main Window — QStackedWidget page navigation
"""

from PySide6.QtWidgets import QMainWindow, QStackedWidget, QWidget, QVBoxLayout
from PySide6.QtCore import Qt, Signal

from rac.database.rac_database import RACDatabase
from rac.state.rac_state_manager import RACStateManager
from andaime.config import ConfigManager
from andaime.qt import ShortcutManager

from rac.gui.constants import TIPO_LABELS
from rac.gui.pages.start_page import StartPage
from rac.gui.pages.entry_page import EntryPage
from rac.gui.pages.preview_page import PreviewPage
from rac.gui.pages.medicamentos_page import MedicamentosPage
from rac.gui.pages.pacientes_page import PacientesPage
from rac.gui.pages.stats_page import StatsPage
from rac.gui.pages.patient_page import PatientPage


class MainWindow(QMainWindow):
    theme_changed = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("RAC - Registros Alto Custo")
        self.setMinimumSize(750, 600)
        self.resize(900, 700)

        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)

        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._stack = QStackedWidget()
        layout.addWidget(self._stack)

        self._pages: dict[str, QWidget] = {}

        self.db: RACDatabase | None = None
        self.state: RACStateManager | None = None
        self.config: ConfigManager | None = None
        self._services = None
        self._last_patient_id: int | None = None
        self._last_preview_tipo: str | None = None

    def init_backend(self):
        self.config = ConfigManager()
        self.db = RACDatabase()
        self.state = RACStateManager()
        self._services = None

        saved_theme = self.config.get("theme", "light")
        from rac.gui.styles import set_theme

        set_theme(saved_theme)

        stay_on_page = self.config.get("stay_on_page", False)
        self.state.set_stay_on_page(stay_on_page)

        last_malote_id = self.config.get("last_malote_id")
        if last_malote_id:
            malote = self.db.get_malote_by_id(last_malote_id)
            if malote:
                self.state.set_active_malote(malote)

        self._setup_shortcuts()

    def _toggle_shortcut_peek(self, show: bool):
        """Delega o peek à página atual (callback do ShortcutManager)."""
        page = self._current_page()
        if page and hasattr(page, "set_shortcuts_visible"):
            page.set_shortcuts_visible(show)

    @property
    def services(self):
        if self._services is None:
            from rac.services.registro_service import RegistroService
            from rac.services.paciente_service import PacienteService
            from rac.services.malote_service import MaloteService
            from rac.services.item_catalog_service import ItemCatalogService
            self._services = type("Services", (), {
                "registro": RegistroService(self.db),
                "paciente": PacienteService(self.db),
                "malote": MaloteService(self.db),
                "item_catalog": ItemCatalogService(self.db),
            })()
        return self._services

    def shutdown_backend(self):
        if self.state and self.config:
            malote = self.state.get_active_malote()
            if malote:
                self.config.set("last_malote_id", malote.id)
            self.config.set("stay_on_page", self.state.get_stay_on_page())
        if self.db:
            self.db.close()

    def navigate_to(self, page_name: str, **kwargs):
        self.shortcuts.reset_peek()
        if page_name == "start":
            self._show_start_page()
        elif page_name == "patient":
            paciente_id = kwargs.get("paciente_id") or self._last_patient_id
            highlight = kwargs.get("highlight_registro")
            return_to = kwargs.get("return_to")
            if paciente_id:
                self._last_patient_id = paciente_id
                self._show_patient_page(paciente_id, highlight, return_to)
        elif page_name == "entry":
            tipo = kwargs.get("tipo", "entrada")
            edit_id = kwargs.get("edit_id")
            return_to = kwargs.get("return_to", "start")
            paciente_id = kwargs.get("paciente_id")
            patient_return_to = kwargs.get("patient_return_to", "start")
            self._show_entry_page(tipo, edit_id, return_to, paciente_id, patient_return_to)
        elif page_name == "preview":
            self._show_preview_page()
        elif page_name == "medicamentos":
            self._show_medicamentos_page()
        elif page_name == "pacientes":
            self._show_pacientes_page()
        elif page_name == "stats":
            self._show_stats_page()

    def _show_start_page(self):
        for i in range(self._stack.count()):
            w = self._stack.widget(i)
            if isinstance(w, StartPage):
                w.refresh()
                self._stack.setCurrentWidget(w)
                return

        page = StartPage(self)
        self._stack.addWidget(page)
        self._stack.setCurrentWidget(page)

    def _clear_above_start(self):
        while self._stack.count() > 1:
            w = self._stack.widget(self._stack.count() - 1)
            if w is None:
                break
            self._stack.removeWidget(w)
            w.deleteLater()

    def _push_page(self, page_class, *args, **kwargs):
        self._clear_above_start()
        page = page_class(self, *args, **kwargs)
        self._stack.addWidget(page)
        self._stack.setCurrentWidget(page)

    def _show_entry_page(
        self, tipo: str, edit_id: int | None = None, return_to: str = "start",
        paciente_id: int | None = None, patient_return_to: str = "start",
    ):
        self._push_page(EntryPage, tipo, edit_id, return_to, paciente_id, patient_return_to)

    def _show_preview_page(self):
        self._push_page(PreviewPage)

    def _show_medicamentos_page(self):
        self._push_page(MedicamentosPage)

    def _show_pacientes_page(self):
        self._push_page(PacientesPage)

    def _show_stats_page(self):
        self._push_page(StatsPage)

    def _show_patient_page(self, paciente_id: int, highlight_registro: int | None = None, return_to: str | None = None):
        self._push_page(PatientPage, paciente_id, highlight_registro, return_to or "start")

    def _setup_shortcuts(self):
        self.shortcuts = ShortcutManager(self)
        self.shortcuts.on_peek(self._toggle_shortcut_peek)

        self.shortcuts.bind("Ctrl+S", self._shortcut_save)
        self.shortcuts.bind("Ctrl+E", self._shortcut_export)
        self.shortcuts.bind(Qt.Key.Key_Escape, self._shortcut_back)
        self.shortcuts.bind("Ctrl+D", self._shortcut_malote_dialog)
        self.shortcuts.bind("Ctrl+R", self._shortcut_focus_search)
        self.shortcuts.bind("Ctrl+G", self._shortcut_preview)
        self.shortcuts.bind("Ctrl+M", self._shortcut_medicamentos)
        self.shortcuts.bind("Ctrl+P", self._shortcut_pacientes)
        self.shortcuts.bind("Ctrl+F", self._shortcut_add_item)
        self.shortcuts.bind("Ctrl+W", self._shortcut_toggle_docs)
        self.shortcuts.bind("Ctrl+Q", self._shortcut_toggle_stay_on_page)
        self.shortcuts.bind("Ctrl+Y", self._shortcut_stats)

        for idx, tipo in enumerate(TIPO_LABELS):
            def handler(_checked=False, t=tipo):
                self._shortcut_tipo_by_key(t)
            self.shortcuts.bind(f"Ctrl+{idx + 1}", handler)

    def _current_page(self):
        return self._stack.currentWidget()

    def _on_page(self, page_class, fn):
        page = self._current_page()
        if isinstance(page, page_class):
            fn(page)

    def _shortcut_save(self):
        self._on_page(EntryPage, lambda p: p._on_save())

    def _shortcut_export(self):
        self._on_page(StartPage, lambda p: p._on_export())

    def _shortcut_back(self):
        page = self._current_page()
        if isinstance(page, (EntryPage, PatientPage)):
            self.navigate_to(page._return_to)
        elif isinstance(page, (PreviewPage, MedicamentosPage, PacientesPage, StatsPage)):
            self.navigate_to("start")

    def _shortcut_malote_dialog(self):
        page = self._current_page()
        if hasattr(page, '_malote_label'):
            page._malote_label.open_dialog()

    def _shortcut_focus_search(self):
        page = self._current_page()
        if isinstance(page, StartPage):
            page._search_combo.focus_search()
        elif isinstance(page, EntryPage):
            page.focus_next_field()
        elif isinstance(page, (MedicamentosPage, PacientesPage)):
            search = page._crud.search
            search.setFocus()
            search.selectAll()
        elif isinstance(page, PreviewPage):
            search = page._tab_searches.get(page._tabs.currentIndex())
            if search:
                search.setFocus()
                search.selectAll()

    def _shortcut_add_item(self):
        def _do(p):
            combo = p._add_item_row()
            if combo:
                combo.focus_search()
        self._on_page(EntryPage, _do)

    def _shortcut_toggle_docs(self):
        self._on_page(EntryPage, lambda p: p._docs_check.toggle())

    def _shortcut_toggle_stay_on_page(self):
        self._on_page(EntryPage, lambda p: p._auto_switch.toggle())

    def _navigate_from_start(self, target: str):
        self._on_page(StartPage, lambda p: self.navigate_to(target))

    def _shortcut_preview(self):
        self._navigate_from_start("preview")

    def _shortcut_medicamentos(self):
        self._navigate_from_start("medicamentos")

    def _shortcut_pacientes(self):
        self._navigate_from_start("pacientes")

    def _shortcut_stats(self):
        self._navigate_from_start("stats")

    def _shortcut_tipo_by_key(self, tipo: str):
        if self.state and self.state.has_active_malote():
            self._on_page(StartPage, lambda p: p._on_tipo_click(tipo))
        self._on_page(EntryPage, lambda p: p._tipo_combo.set_tipo(tipo))

        def _set_tab(p):
            idx = list(TIPO_LABELS.keys()).index(tipo)
            if p._tabs and idx < p._tabs.count():
                p._tabs.setCurrentIndex(idx)
        self._on_page(PreviewPage, _set_tab)

    def closeEvent(self, event):
        self.shutdown_backend()
        super().closeEvent(event)
