"""Emissor de Recibos — janela principal PySide6 (Qt)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import os

from andaime.qt import ShortcutManager
from andaime.db_worker import DatabaseWorker
from andaime.error_handler import ErrorContext, ErrorHandler, ErrorLevel
from emissor.database.emissor_db import EmissorDatabase
from emissor.database.models import Patient
from emissor.services.patient_service import PatientService
from emissor.services.retirada_service import RetiradaService
from emissor.services.retirada_workflow_service import (
    PreparedRetirada,
    RetiradaRequest,
    RetiradaWorkflowService,
)
from emissor.services.scanner_service import (
    ScannerError,
    ScannerService,
)
from emissor.services.exceptions import (
    DuplicatePatientError,
    PDFGenerationError,
    RetiradaSaveError,
    ValidationError,
)
from emissor.services.printer import print_pdf, PrintResult
from emissor.utils.file_utils import open_file
from andaime.qt import DbAsyncRunner, StatusLine
from emissor.utils.paths import resolve_archive_dir
from emissor.utils.security import sanitize_filename
from andaime.shutdown import register_cleanup

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QGridLayout,
    QMainWindow,
    QVBoxLayout,
    QWidget,
)

from emissor.state import DirtyTracker, StateManager
from emissor.ui_qt.theme import get_palette, qpalette, set_theme, stylesheet

# ============================================================================
# Pesos do grid
# ============================================================================

_COL_PATIENT = 5
_COL_OPTIONS = 6
_COL_RIGHT = 3
_ROW_TOP = 5
_ROW_BOTTOM = 5
_STRETCH_DATES = 7
_STRETCH_ACTIONS = 5


class QtApp(QMainWindow):
    """Janela principal da aplicação em PySide6."""

    def __init__(self, andaime_instance: Any) -> None:
        """Inicializa a janela principal."""
        super().__init__()

        self.setWindowTitle("Emissor de Recibos")
        self.resize(1280, 720)
        self.showMaximized()

        # ===== Backend =====
        self._emissor_db: EmissorDatabase = andaime_instance.db
        self._root: Path = andaime_instance.root
        self._patient_service = PatientService(self._emissor_db)
        self._retirada_service = RetiradaService(self._emissor_db)
        self._pdf_generator: Any = None
        # Workflow service é instanciado depois de state_manager/config (abaixo)
        self._workflow_service: RetiradaWorkflowService | None = None
        register_cleanup(self._emissor_db.close, "emissor_database_qt")

        # DB off-main-thread: worker dedicado (serializa a conexão) + bridge Qt
        # que devolve resultados na thread principal via signal. Drenado em
        # closeEvent antes do close() do banco (ver _drain_db_worker).
        self._db_worker = DatabaseWorker(self._emissor_db)
        self._db_runner = DbAsyncRunner(self._db_worker)

        self.config_manager = andaime_instance.config
        self.state_manager = StateManager()
        self.state_manager.set_save_root_path(self.config_manager.get("save_location"))
        self.state_manager.set_print_copies(self.config_manager.get("print_copies"))

        self._current_dark_mode = self.config_manager.get("dark_mode", True)
        self.state_manager.set_dark_mode(self._current_dark_mode)
        set_theme("dark" if self._current_dark_mode else "light")

        self.dirty_tracker = DirtyTracker()
        self._workflow_service = RetiradaWorkflowService(
            self._retirada_service,
            self.state_manager,
            self.config_manager,
            self._emissor_db,
        )

        self._status_label: StatusLine | None = None
        self._pending_auto_print: bool = False

        # ===== UI =====
        self._build_ui()
        self._setup_shortcuts()

        ErrorHandler.log(
            "Interface Qt carregada",
            level=ErrorLevel.INFO,
            context=ErrorContext.UI,
        )

    # ========== Properties (interface usada pelas seções) ==========

    @property
    def db(self) -> EmissorDatabase:
        """Retorna o banco de dados."""
        return self._emissor_db

    @property
    def patient_service(self) -> PatientService:
        """Retorna o serviço de paciente."""
        return self._patient_service

    @property
    def retirada_service(self) -> RetiradaService:
        """Retorna o serviço de retirada."""
        return self._retirada_service

    @property
    def db_runner(self) -> DbAsyncRunner:
        """Runner para executar DB ops fora da thread principal (resultos via signal)."""
        return self._db_runner

    @property
    def pdf_generator(self) -> Any:
        """Lazy-load do gerador de PDF."""
        if not hasattr(self, "_pdf_generator") or self._pdf_generator is None:
            from emissor.pdf.pdf_generator_reportlab import ReportLabPDFGenerator

            self._pdf_generator = ReportLabPDFGenerator()
            self._retirada_service.set_pdf_generator(self._pdf_generator)
        return self._pdf_generator

    # ========== UI Construction ==========

    def _build_ui(self) -> None:
        """Constrói o esqueleto da interface: barra de busca + grid."""
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(8)

        root.addWidget(self._build_search_bar(), stretch=0)
        root.addWidget(self._build_status_label(), stretch=0)
        root.addWidget(self._build_content_grid(), stretch=1)

    def _build_search_bar(self) -> QWidget:
        """Constrói a barra superior (SearchSection)."""
        from emissor.ui_qt.sections.search_section import SearchSection

        self.search_section = SearchSection(self.centralWidget(), self)
        return self.search_section

    def _build_status_label(self) -> StatusLine:
        """Cria a linha de status global (centralizada, atualizada via set_status)."""
        self._status_label = StatusLine()
        return self._status_label

    def set_status(
        self,
        text: str,
        color: str | None = None,
        path: str | None = None,
    ) -> None:
        """Define o texto do status global.

        Args:
            color: hex ou chave do tema (ex.: "status_success"); None = padrão
            path: caminho de arquivo/pasta opcional; quando informado a linha
                fica sublinhada e clicável, abrindo o explorador no caminho.
        """
        if self._status_label is not None:
            self._status_label.set_status(text, color, path)

    def _build_content_grid(self) -> QWidget:
        """Constrói o grid principal de conteúdo com as seções."""
        content = QWidget()
        grid = QGridLayout(content)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(8)

        grid.setColumnStretch(0, _COL_PATIENT)
        grid.setColumnStretch(1, _COL_OPTIONS)
        grid.setColumnStretch(2, _COL_RIGHT)
        grid.setRowStretch(0, _ROW_TOP)
        grid.setRowStretch(1, _ROW_BOTTOM)

        # Row 0: Patient | Options
        # PatientSection - row 0, column 0
        from emissor.ui_qt.sections.patient_section import PatientSection

        self.patient_section = PatientSection(content, self)
        grid.addWidget(self.patient_section, 0, 0)

        # OptionsSection - row 0, column 1
        from emissor.ui_qt.sections.options_section import OptionsSection

        self.options_section = OptionsSection(content, self)
        grid.addWidget(self.options_section, 0, 1)

        # Right panel (rows 0-1, col 2): Dates + Actions
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        # DatesSection - right_panel row 0
        from emissor.ui_qt.sections.dates_section import DatesSection

        self.dates_section = DatesSection(right_panel, self)
        right_layout.addWidget(self.dates_section, stretch=_STRETCH_DATES)

        # ActionsSectionV3 - right_panel row 1
        from emissor.ui_qt.sections.actions_section import ActionsSection

        self.actions_section = ActionsSection(right_panel, self)
        right_layout.addWidget(self.actions_section, stretch=_STRETCH_ACTIONS)

        # Actions observa o dirty tracker (atualiza contador do botão Salvar)
        self.dirty_tracker.add_observer(self.actions_section)

        grid.addWidget(right_panel, 0, 2, 2, 1)

        # Row 1: Items (span cols 0-1)
        # ItemsSectionV3 - row 1, column 0, spans 2 columns
        from emissor.ui_qt.sections.items_section import ItemsSection

        self.items_section = ItemsSection(content, self)
        grid.addWidget(self.items_section, 1, 0, 1, 2)

        return content

    def _setup_shortcuts(self) -> None:
        """Registra atalhos de teclado com dicas visuais (peek via Ctrl+Shift)."""
        self.shortcuts = ShortcutManager(self)
        self.shortcuts.bind(
            "Ctrl+S", self.save_patient_data, self.actions_section._save_data_btn
        )
        self.shortcuts.bind(
            "Ctrl+G", self.handle_print, self.actions_section._print_btn
        )
        self.shortcuts.bind(
            "Ctrl+F", self.handle_open_pdf, self.actions_section._open_pdf_btn
        )
        self.shortcuts.bind("Ctrl+D", self.handle_scan, self.actions_section._scan_btn)
        self.shortcuts.bind("Ctrl+R", self.search_section.focus_search)

    # ========== Tema ==========

    def _on_theme_toggled(self, dark_mode: bool) -> None:
        """Trata toggle de tema: persiste, atualiza estado e reaplica QSS."""
        self._current_dark_mode = dark_mode
        set_theme("dark" if dark_mode else "light")
        palette = get_palette(dark_mode)

        qapp = QApplication.instance()
        if isinstance(qapp, QApplication):
            qapp.setPalette(qpalette(palette))
            qapp.setStyleSheet(stylesheet(palette))

        self.config_manager.set("dark_mode", dark_mode)
        self.state_manager.set_dark_mode(dark_mode)

    # ========== Ações (chamadas pela barra de busca) ==========

    def open_config_dialog(self) -> None:
        """Abre o diálogo de configuração e aplica o resultado ao salvar."""
        from emissor.ui_qt.config_dialog import QtConfigDialog

        current = {
            "save_location": self.state_manager.get_save_root_path(),
            "print_copies": self.state_manager.get_print_copies(),
            "dark_mode": self.state_manager.get_dark_mode(),
            "distribute_retiradas": self.config_manager.get(
                "distribute_retiradas", True
            ),
            "distribution_window_days": self.config_manager.get(
                "distribution_window_days", 3
            ),
        }

        dialog = QtConfigDialog(self, current, self.launch_dashboard)
        if dialog.exec() and dialog.result_data is not None:
            self._apply_config(dialog.result_data)

    def _apply_config(self, config: dict[str, Any]) -> None:
        """Persiste e aplica a configuração proveniente do diálogo."""
        self.config_manager.set("save_location", config["save_location"])
        self.config_manager.set("print_copies", config["print_copies"])
        self.config_manager.set("dark_mode", config["dark_mode"])
        self.config_manager.set("distribute_retiradas", config["distribute_retiradas"])
        self.config_manager.set(
            "distribution_window_days", config["distribution_window_days"]
        )

        self.state_manager.set_save_root_path(config["save_location"])
        self.state_manager.set_print_copies(config["print_copies"])

    # ========== Workflow de salvamento / PDF ==========

    def _finalize_active_edits(self) -> None:
        """Finaliza edições in-line pendentes nas seções."""
        self.patient_section.finish_edit()
        self.items_section.finish_edit()

    def collect_form_data(self) -> dict[str, Any]:
        """Coleta dados de todas as seções para workflows de salvamento/PDF."""
        dates = self.dates_section.get_date_entries()
        patient_data = self.patient_section.get_patient_data()
        options_data = self.options_section.get_options_data()

        return {
            "patient_id": self.state_manager.get_patient_id(),
            "patient_name": self.state_manager.get_patient_name(),
            "processos": self.patient_section.get_all_processos(),
            **patient_data,
            **options_data,
            "itens": self.items_section.get_items_data(),
            "datas": {
                "hoje": dates["hoje"],
                "proxima_vez": dates["proxima_vez"],
                "validade_receita": dates["validade_receita"],
                "ultima_receita": options_data.get("ultima_receita", ""),
            },
        }

    def _build_retirada_request(self) -> RetiradaRequest | None:
        """Coleta dados das seções, pré-calcula datas e monta RetiradaRequest."""
        data = self.collect_form_data()
        _, date_str = self.dates_section.get_data_retirada_for_pdf()

        # Pré-calcular datas na thread da UI (notifica observers Qt).
        data_retirada_str = data["datas"]["hoje"]
        self._workflow_service.ensure_dates_computed(data_retirada_str)
        proxima_vez = self.state_manager.get_calculated_dates().get("proxima_vez")

        save_root = self.state_manager.get_save_root_path()
        if save_root is None:
            return None

        return RetiradaRequest(
            selected_patient=self.state_manager.get_selected_patient(),
            data=data,
            save_root=Path(save_root),
            proxima_vez=proxima_vez,
            data_retirada_for_pdf=date_str,
            ignorar_itens=self.items_section.get_reset_item_keys(),
        )

    def _generate_pdf_workflow(self, auto_print: bool = False) -> None:
        """Workflow central de geração de PDF — assíncrono via db_runner.

        Args:
            auto_print: se True, envia para impressora após salvar
        """
        self._finalize_active_edits()

        if self._workflow_service is None:
            self.search_section.set_status(
                "Serviço de workflow não inicializado", color="status_error"
            )
            return

        # Validação rápida na thread da UI (campos obrigatórios).
        request = self._build_retirada_request()
        if request is None:
            self.search_section.set_status(
                "Local de salvamento não configurado.", color="status_error"
            )
            return

        self.search_section.set_status("Gerando PDF...", color="status_warning")
        self._pending_auto_print = auto_print
        self.actions_section.set_pdf_actions_busy(True)

        # Submeter prepare + commit ao worker thread.
        pdf_gen = self.pdf_generator

        def _work(req: RetiradaRequest) -> PreparedRetirada:
            prepared = self._workflow_service.prepare(req, pdf_gen)
            self._workflow_service.commit(prepared)
            return prepared

        self._db_runner.run(
            _work,
            request,
            on_done=self._on_pdf_done,
            on_error=self._on_pdf_error,
        )

    def _on_pdf_done(self, prepared: PreparedRetirada) -> None:
        """Callback de sucesso do workflow de PDF (thread da UI)."""
        self.actions_section.set_pdf_actions_busy(False)
        self.state_manager.set_last_generated_pdf(
            str(prepared.pdf_path), patient_id=prepared.patient_id
        )
        self.actions_section.enable_open_pdf_button()
        from andaime.qt import relative_path

        status_path = relative_path(
            self.state_manager.get_save_root_path(), prepared.pdf_path
        )
        self.search_section.set_status(
            text=f"PDF salvo - {status_path}",
            color="status_success",
            path=str(prepared.pdf_path),
        )
        self.dates_section.check_existing_retirada()
        self.dates_section.refresh_ultima_retirada()
        self.items_section.clear_reset_toggles()

        if getattr(self, "_pending_auto_print", False):
            self._print_pdf(str(prepared.pdf_path))

    def _on_pdf_error(self, exc: BaseException) -> None:
        """Callback de erro do workflow de PDF (thread da UI)."""
        self.actions_section.set_pdf_actions_busy(False)
        if isinstance(exc, ValidationError):
            self.search_section.set_status(str(exc), color="status_error")
        elif isinstance(exc, FileNotFoundError):
            ErrorHandler.handle_error(exc, context=ErrorContext.FILE_IO)
            self.search_section.set_status(str(exc), color="status_error")
        elif isinstance(exc, PDFGenerationError):
            ErrorHandler.handle_error(exc, context=ErrorContext.PDF_GENERATION)
            self.search_section.set_status("Falha ao gerar PDF", color="status_error")
        elif isinstance(exc, OSError):
            ErrorHandler.handle_file_error(exc, file_path="", operation="save")
            self.search_section.set_status(
                f"Erro de rede ao salvar: {exc}", color="status_error"
            )
        elif isinstance(exc, (RetiradaSaveError,)):
            ErrorHandler.log(
                str(exc), level=ErrorLevel.ERROR, context=ErrorContext.DATABASE
            )
            self.search_section.set_status(
                "PDF gerado, mas falha ao salvar no banco", color="status_error"
            )
        else:
            ErrorHandler.handle_error(exc, context=ErrorContext.PDF_GENERATION)
            self.search_section.set_status(
                f"Erro inesperado: {exc}", color="status_error"
            )

    def _print_pdf(self, pdf_path: str) -> None:
        """Envia o PDF para impressão de forma assíncrona via db_runner."""
        copies = self.state_manager.get_print_copies()
        patient_name = self.state_manager.get_patient_name() or "Paciente"
        self.search_section.set_status("Imprimindo...", color="status_warning")

        self._db_runner.run(
            print_pdf,
            pdf_path,
            copies,
            f"Emissor - {patient_name}",
            on_done=lambda result: self._on_print_done(
                result, pdf_path, patient_name, copies
            ),
        )

    def _on_print_done(
        self,
        result: PrintResult,
        pdf_path: str,
        patient_name: str,
        copies: int,
    ) -> None:
        """Callback de impressão (thread da UI); abre PDF em caso de falha."""
        copies_text = f"{copies} cópia" if copies == 1 else f"{copies} cópias"

        if result.ok:
            self.search_section.set_status(
                text=f"Enviado para impressão ({copies_text}) - {patient_name}",
                color="status_success",
            )
            return

        ErrorHandler.log(
            f"Impressão falhou [{result.status.value}] via {result.backend}: "
            f"{result.message}",
            level=ErrorLevel.WARNING,
            context=ErrorContext.UI,
        )
        self.search_section.set_status(
            text=f"{result.message} Abrindo PDF para impressão manual...",
            color="status_warning",
        )
        try:
            open_file(pdf_path)
        except OSError as e:
            ErrorHandler.handle_file_error(e, file_path=str(pdf_path), operation="open")

    def save_patient_data(self) -> None:
        """Salva os dados editados do paciente no banco de dados."""
        self._finalize_active_edits()

        patient_data = self.patient_section.get_patient_data()
        options_data = self.options_section.get_options_data()
        items_data = self.items_section.get_items_data()

        if not self.state_manager.has_selected_patient():
            nome = patient_data.get("nome", "")
            if not nome:
                ErrorHandler.log(
                    "Nome do paciente é obrigatório para criar novo paciente",
                    level=ErrorLevel.WARNING,
                    context=ErrorContext.VALIDATION,
                )
                return

            try:
                result = self._patient_service.create_patient(nome)
            except DuplicatePatientError:
                from PySide6.QtWidgets import QMessageBox

                QMessageBox.warning(
                    self,
                    "Paciente Já Existe",
                    (
                        f"Já existe um paciente cadastrado com o nome '{nome}'.\n\n"
                        f"Use a busca para selecionar o paciente existente."
                    ),
                )
                ErrorHandler.log(
                    f"Tentativa de criar paciente duplicado: {nome}",
                    level=ErrorLevel.WARNING,
                    context=ErrorContext.VALIDATION,
                )
                return
            except ValidationError as e:
                ErrorHandler.log(
                    str(e),
                    level=ErrorLevel.WARNING,
                    context=ErrorContext.VALIDATION,
                )
                return

            # Não seleciona o Patient vazio aqui: PATIENT_SELECTED limparia
            # o formulário. Salva com o id retornado e reseleciona no fim.
            is_new_patient = True
            patient_id = result.patient_id
            current_patient = None

            self.patient_section.set_name_id_editable(False)
            self.search_section.set_status(
                text=f"Paciente criado: {result.patient_name} (ID: {result.patient_id})",
                color="status_success",
            )
        else:
            is_new_patient = False
            current_patient = self.state_manager.get_selected_patient()
            patient_id = self.state_manager.get_patient_id()

        data_to_save: dict[str, Any] = patient_data
        data_to_save.update(options_data)
        data_to_save["itens"] = items_data

        if patient_id is not None and data_to_save:
            try:
                save_result = self._patient_service.save_patient_data(
                    patient_id, data_to_save, current_patient
                )
            except ValidationError as e:
                ErrorHandler.log(
                    str(e),
                    level=ErrorLevel.WARNING,
                    context=ErrorContext.VALIDATION,
                )
                return

            if is_new_patient:
                saved_patient = self.db.get_patient_by_id(patient_id)
                if saved_patient is not None:
                    self.state_manager.set_selected_patient(saved_patient)
            else:
                self.state_manager.update_selected_patient(data_to_save)
            self.search_section.set_status(
                text=f"Dados salvos! - {save_result.patient_name}",
                color="status_success",
            )
            self.dirty_tracker.mark_clean()
        else:
            ErrorHandler.log(
                "Nenhum dado para salvar",
                level=ErrorLevel.WARNING,
                context=ErrorContext.VALIDATION,
            )

    def handle_print(self) -> None:
        """Gera PDF e envia para impressora."""
        self._generate_pdf_workflow(auto_print=True)

    def handle_save_pdf(self) -> None:
        """Gera PDF e salva no disco."""
        self._generate_pdf_workflow(auto_print=False)

    def handle_open_pdf(self) -> None:
        """Abre o último PDF gerado para o paciente selecionado."""
        patient = self.state_manager.get_selected_patient()
        if not patient:
            ErrorHandler.handle_error(
                Exception("Nenhum paciente selecionado"),
                context=ErrorContext.VALIDATION,
            )
            return

        # Preferir o último PDF gerado nesta sessão (reflete o estado atual do
        # formulário). Só confia no cache se for do paciente selecionado; caso
        # contrário cai para o caminho derivado do banco.
        last_pdf = self.state_manager.get_last_generated_pdf_for_patient(
            patient.id
        )
        if last_pdf:
            pdf_path = Path(last_pdf)
            if pdf_path.exists():
                try:
                    open_file(str(pdf_path))
                except Exception as e:
                    ErrorHandler.handle_file_error(e, str(pdf_path), "open")
                return
            self.set_status(
                f"Recibo não encontrado: {pdf_path.name}",
                color="status_warning",
            )
            return

        patient_id = patient.id
        retiradas = self.db.get_retiradas_by_patient(patient_id)
        if not retiradas:
            ErrorHandler.handle_error(
                Exception("Nenhum PDF encontrado para este paciente"),
                context=ErrorContext.FILE_IO,
            )
            return

        ultima_retirada = retiradas[0]

        patient_nome = patient.nome
        safe_patient_name = sanitize_filename(patient_nome)

        save_root = self.state_manager.get_save_root_path()
        if save_root is None:
            ErrorHandler.handle_error(
                FileNotFoundError(
                    "Diretório de salvamento não configurado. "
                    "Abra Configurações e defina um local de salvamento."
                ),
                context=ErrorContext.FILE_IO,
            )
            return

        patient_tipo = patient.tipo
        archive_dir = resolve_archive_dir(
            save_root,
            patient_tipo,
            safe_patient_name,
            create=False,
        )
        pdf_path = archive_dir / f"{ultima_retirada.data_retirada}.pdf"

        if pdf_path.exists():
            try:
                open_file(str(pdf_path))
            except Exception as e:
                ErrorHandler.handle_file_error(e, str(pdf_path), "open")
        else:
            self.set_status(
                f"Recibo não encontrado: {pdf_path.name}",
                color="status_warning",
            )

    def handle_scan(self) -> None:
        """Digitaliza documento e salva em RECIBOS ASSINADOS do paciente.

        Usa ``scan_dpi`` e ``scan_color_mode`` do AppConfig. O acquire TWAIN
        roda em QThread dedicado; a cópia para a rede roda no db_worker.
        """
        from PySide6.QtCore import QThread, QObject, Signal, Slot

        patient = self.state_manager.get_selected_patient()
        if patient is None:
            self.search_section.set_status(
                "Selecione um paciente antes de digitalizar.", color="status_error"
            )
            return

        _, date_str = self.dates_section.get_data_retirada_for_pdf()
        if not date_str:
            self.search_section.set_status(
                "Defina a data da retirada antes de digitalizar.",
                color="status_error",
            )
            return

        save_root = self.state_manager.get_save_root_path()
        if not save_root:
            self.search_section.set_status(
                "Local de salvamento não configurado.", color="status_error"
            )
            return

        dpi = int(self.config_manager.get("scan_dpi", 200))
        color_mode = self.config_manager.get("scan_color_mode", "grayscale")

        service = ScannerService(save_root=Path(save_root))

        self.search_section.set_status("Digitalizando...", color="status_warning")
        self.actions_section.disable_scan_button()

        # Guardar contexto para a fase de network copy.
        self._scan_context = {
            "service": service,
            "tipo": patient.tipo,
            "nome": patient.nome,
            "date_str": date_str,
        }

        # TWAIN acquire num QThread com event loop (message pump).
        class _AcquireWorker(QObject):
            finished = Signal(object)  # Path
            error = Signal(object)  # BaseException

            def __init__(self, svc, d, cm):
                super().__init__()
                self._svc = svc
                self._dpi = d
                self._color = cm

            @Slot()
            def run(self):
                try:
                    local = self._svc.acquire_locally(
                        dpi=self._dpi, color_mode=self._color
                    )
                    self.finished.emit(local)
                except BaseException as exc:
                    self.error.emit(exc)

        self._scan_thread = QThread(self)
        self._scan_worker = _AcquireWorker(service, dpi, color_mode)
        self._scan_worker.moveToThread(self._scan_thread)
        self._scan_thread.started.connect(self._scan_worker.run)
        self._scan_worker.finished.connect(self._on_acquire_finished)
        self._scan_worker.error.connect(self._on_acquire_error)
        # Auto-cleanup do thread/worker.
        self._scan_worker.finished.connect(self._scan_thread.quit)
        self._scan_worker.error.connect(self._scan_thread.quit)
        self._scan_thread.finished.connect(self._scan_worker.deleteLater)
        self._scan_thread.finished.connect(self._scan_thread.deleteLater)
        self._scan_thread.start()

    def _on_acquire_finished(self, local_tmp: Path) -> None:
        """Acquire concluído — agenda a cópia para a rede no db_worker."""
        ctx = getattr(self, "_scan_context", None)
        if ctx is None:
            return

        self.search_section.set_status("Salvando na rede...", color="status_warning")

        self._db_runner.run(
            ctx["service"].copy_to_network,
            local_tmp,
            ctx["tipo"],
            ctx["nome"],
            ctx["date_str"],
            on_done=self._on_scan_done,
            on_error=self._on_scan_error,
        )

    def _handle_scan_error(self, exc: BaseException, status_msg: str) -> None:
        """Reabilita o botão e reporta erro de digitalização na UI."""
        if self.state_manager.has_selected_patient():
            self.actions_section.enable_scan_button()
        if isinstance(exc, ScannerError):
            self.search_section.set_status(str(exc), color="status_error")
            ErrorHandler.handle_error(Exception(str(exc)), context=ErrorContext.FILE_IO)
        else:
            ErrorHandler.handle_error(exc, context=ErrorContext.FILE_IO)
            self.search_section.set_status(status_msg, color="status_error")

    def _on_acquire_error(self, exc: BaseException) -> None:
        """Erro durante o acquire TWAIN — roda na thread da UI."""
        self._handle_scan_error(exc, f"Erro ao digitalizar: {exc}")

    def _on_scan_done(self, pdf_path: Path) -> None:
        """Callback de sucesso da network copy — roda na thread da UI."""
        if self.state_manager.has_selected_patient():
            self.actions_section.enable_scan_button()
        from andaime.qt import relative_path

        status_path = relative_path(
            self.state_manager.get_save_root_path(), pdf_path
        )
        self.search_section.set_status(
            text=f"Digitalizado: {status_path}",
            color="status_success",
            path=str(pdf_path),
        )

    def _on_scan_error(self, exc: BaseException) -> None:
        """Callback de erro da network copy — roda na thread da UI."""
        if isinstance(exc, OSError):
            self.search_section.set_status(
                f"Erro de rede ao digitalizar: {exc}", color="status_error"
            )
            ErrorHandler.handle_file_error(exc, file_path="", operation="save")
            if self.state_manager.has_selected_patient():
                self.actions_section.enable_scan_button()
        else:
            self._handle_scan_error(exc, f"Erro ao digitalizar: {exc}")

    def launch_agenda(self) -> None:
        """Abre a Agenda interna como janela filha."""
        from emissor.ui_qt.agenda_window import open_agenda

        open_agenda(self, self.db, self.config_manager, self._root)

    def launch_dashboard(self) -> None:
        """Abre o Dashboard interno como janela filha."""
        from emissor.ui_qt.dashboard_window import open_dashboard

        existing = getattr(self, "_dashboard_window", None)
        if existing is not None and existing.isVisible():
            existing.raise_()
            existing.activateWindow()
            return
        self._dashboard_window = open_dashboard(self, self.config_manager)

    def restart_app(self) -> None:
        """Reinicia a aplicação."""
        import subprocess

        try:
            if getattr(sys, "frozen", False):
                subprocess.Popen([sys.executable], start_new_session=True)
            else:
                pkg_dir = Path(__file__).resolve().parent
                # O launcher roda "<python> -m emissor" a partir do diretório
                # que contém o pacote. Replicamos exatamente para manter o
                # mesmo PYTHONPATH/cwd da inicialização.
                if (pkg_dir / "__init__.py").exists():
                    module = pkg_dir.name
                    work_dir = pkg_dir.parent
                else:
                    module = "main"
                    work_dir = pkg_dir
                subprocess.Popen(
                    [sys.executable, "-m", module],
                    cwd=str(work_dir),
                    env={**os.environ, "PYTHONPATH": str(work_dir)},
                    start_new_session=True,
                )
            self.close()
        except Exception as e:
            ErrorHandler.handle_error(e, context=ErrorContext.UI)

    # ========== Ciclo de vida ==========

    def _cleanup_sections(self) -> None:
        """Desregistra todas as seções QtSection do StateManager."""
        for attr in (
            "search_section",
            "patient_section",
            "options_section",
            "dates_section",
            "items_section",
            "actions_section",
        ):
            section = getattr(self, attr, None)
            cleanup = getattr(section, "cleanup", None)
            if callable(cleanup):
                try:
                    cleanup()
                except Exception:
                    pass

    def closeEvent(self, event: QCloseEvent) -> None:
        """Desregistra observers ao fechar."""
        self._drain_db_worker()
        self._cleanup_sections()
        super().closeEvent(event)

    def _drain_db_worker(self) -> None:
        """Encerra o worker de DB aguardando tarefas pendentes.

        Roda ANTES do close() do banco para que operações em voo completem.
        """
        worker = getattr(self, "_db_worker", None)
        if worker is not None:
            try:
                worker.shutdown(wait=True)
            except Exception as e:
                ErrorHandler.log(
                    f"Erro ao encerrar DB worker: {e}",
                    level=ErrorLevel.WARNING,
                    context=ErrorContext.SHUTDOWN,
                )
