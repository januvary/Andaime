import copy

from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt, Signal
from andaime.qt import ShortcutManager

from bap.database.ss54_database import SS54Database
from andaime.config import ConfigManager
from bap.utils.text_utils import normalize_phone
from bap.ui_qt.styles import set_theme, get_stylesheet, get_palette, qpalette
from bap.ui_qt.widgets.document_page import DocumentPage
from bap.ui_qt.widgets.remessas_page import RemessasPage
from bap.ui_qt.remessa_sender import RemessaSender
from bap.models import GridItem, Paciente, Processo
from bap.constants import (
    NULL_STATUS,
    RENOVACAO_DOC_EXCLUSIONS,
    Status,
    status_display_label,
)
from bap.utils.config import bap_data_dir
from bap.utils.date_utils import format_date_display
from bap.utils.arquivo_storage import resolve_arquivos_root


class MainWindow(QMainWindow):
    theme_changed = Signal()

    def __init__(self, app_instance):
        super().__init__()
        self._app = app_instance
        self.setWindowTitle("BAP — Bancada de Administração de Processos")
        self.resize(1280, 720)
        self.showMaximized()

        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(8)

        self.db: SS54Database | None = None
        self.config: ConfigManager | None = None
        self._db_worker = None
        self._db_runner = None
        self._selected_patient_id: int | None = None
        self._grid_showing_process: bool = False
        self._loading: bool = False
        self._active_lote: "object | None" = None

        self._stack = QStackedWidget()
        self._stack.setObjectName("content")

        self._doc_page = DocumentPage()
        self._remessa_page = RemessasPage()
        self._sender = RemessaSender(self)
        self._stack.addWidget(self._doc_page)
        self._stack.addWidget(self._remessa_page)
        self._stack.setCurrentWidget(self._remessa_page)

        root.addWidget(self._stack, stretch=1)

        self._connect_pages()
        self._setup_shortcuts()
        self.installEventFilter(self)

    def _connect_pages(self) -> None:
        dp = self._doc_page
        rp = self._remessa_page
        dp.patient_selected.connect(self._on_patient_selected)
        dp.theme_toggled.connect(self._on_theme_toggled)
        dp.filtros_changed.connect(self._on_filtros_changed)
        dp.ciclo_changed.connect(self._on_ciclo_changed)
        dp.remessa_changed.connect(self._on_remessa_changed)
        dp.status_changed.connect(self._on_status_changed)
        dp.retornar.connect(self._goto_remessas)
        dp.salvar.connect(self._on_salvar)
        dp.config_requested.connect(self._open_config_dialog)
        rp.retornar.connect(self._goto_document)
        rp.novo_processo.connect(self._goto_novo_processo)
        rp.enviar.connect(self._on_enviar_remessa)
        rp.remessa_changed.connect(self._on_remessa_changed)
        rp.ver_processo.connect(self.open_processo)

        # RemessaSender → UI feedback
        sender = self._sender
        sender.status_changed.connect(self.set_status)
        sender.info.connect(self._info)
        sender.warn.connect(self._warn)
        sender.remessas_changed.connect(self._remessa_page.refresh)

        # Atalhos de backend (mantêm o código existente sem alteração).
        self._header = dp.header
        self._remessa_label = dp.remessa_label
        self._status_selector = dp.status_selector
        self._grid = dp.grid
        self._grid.files_dropped.connect(self._on_files_dropped)
        self._grid.status_message.connect(
            lambda text, color=None: self.set_status(text, color)
        )
        self._grid.set_bytes_loader(self._grid_item_bytes)
        self.theme_changed.connect(dp.grid.refresh_theme)
        self.theme_changed.connect(self._remessa_page.refresh_theme)

    def _setup_shortcuts(self) -> None:
        """Registra atalhos de teclado com dicas visuais (peek via Ctrl+Shift)."""
        self.shortcuts = ShortcutManager(self)

        doc_bar = self._doc_page._bottom_bar
        rem_bar = self._remessa_page._bottom_bar

        self.shortcuts.bind(
            "Ctrl+S", self._on_salvar, doc_bar.action_button("Salvar")
        )
        # Ctrl+F alterna entre páginas (dispatcher pela página atual).
        self.shortcuts.bind("Ctrl+F", self._toggle_page)
        self.shortcuts.register_hint(
            doc_bar.action_button("Retornar"), "Ctrl+F"
        )
        self.shortcuts.register_hint(rem_bar.action_button("Novo Processo"), "Ctrl+F")
        # Ctrl+R foca a busca da página atual.
        self.shortcuts.bind("Ctrl+R", self._focus_search)
        self.shortcuts.bind(
            "Ctrl+E", self._on_enviar_remessa, self._remessa_page._enviar_btn
        )

    def _toggle_page(self) -> None:
        """Ctrl+F: alterna entre as páginas Remessas e Documento."""
        if self._stack.currentWidget() is self._doc_page:
            self._goto_remessas()
        else:
            self._goto_document()

    def _focus_search(self) -> None:
        """Ctrl+R: foca o campo de busca da página atual."""
        if self._stack.currentWidget() is self._doc_page:
            self._doc_page.focus_search()
        else:
            self._remessa_page.focus_search()

    def _goto_remessas(self) -> None:
        self.navigate_to("remessas")
        self._remessa_page.refresh(force=False)
        self._sender.scan_drs_messages()

    def _goto_novo_processo(self) -> None:
        """Vai para a página de documentos iniciando um processo em branco."""
        self._goto_document()
        self._doc_page.header.novo_requested.emit()

    def _goto_document(self) -> None:
        self.navigate_to("document")

    def _on_enviar_remessa(self) -> None:
        if self.db is None or self.config is None:
            return
        lote = self._remessa_page.remessa_active() or self._resolve_active_lote()
        if lote is None:
            self._info("Nenhuma remessa ativa.")
            return
        self._sender.enviar(lote)

    def _info(self, text: str) -> None:
        QMessageBox.information(self, "BAP", text)

    def _warn(self, text: str) -> None:
        QMessageBox.warning(self, "BAP", text)

    def set_status(self, text: str, color: str | None = None) -> None:
        """Define o texto da linha de status da página ativa."""
        self._doc_page.set_status(text, color)
        self._remessa_page.set_status(text, color)

    def _open_config_dialog(self) -> None:
        """Abre o diálogo de configuração (menu de contexto da barra superior)."""
        if self.config is None:
            return

        from bap.ui_qt.widgets.config_dialog import QtConfigDialog
        from bap.utils.arquivo_storage import resolve_arquivos_root

        cfg = self.config.get_all()
        default_root = resolve_arquivos_root(None)
        current = {
            "arquivos_root": self.config.get("arquivos_root", "")
            or str(resolve_arquivos_root(cfg)),
            "default_root": str(default_root),
        }

        dialog = QtConfigDialog(
            self,
            current,
            self._export_planilha,
        )
        if dialog.exec() and dialog.result_data is not None:
            self.config.set("arquivos_root", dialog.result_data["arquivos_root"])
            self.set_status("Configurações salvas.", "status_success")

    def _export_planilha(self, parent) -> None:
        """Exporta os processos para uma planilha Excel (botão do diálogo)."""
        if self.db is None:
            return

        from PySide6.QtWidgets import QFileDialog
        from bap.utils.arquivo_storage import resolve_arquivos_root

        cfg = self.config.get_all() if self.config else None
        default_dir = resolve_arquivos_root(cfg)
        default_path = str(default_dir / "processos_export.xlsx")

        path, _ = QFileDialog.getSaveFileName(
            parent,
            "Exportar planilha",
            default_path,
            "Planilha Excel (*.xlsx)",
        )
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"

        from bap.utils.export_to_xlsx import export_processos_to_xlsx

        self.set_status("Exportando planilha…", "status_warning")

        def _work():
            return export_processos_to_xlsx(self.db, path)

        def _done(saved):
            self.set_status("")
            QMessageBox.information(self, "BAP", f"Planilha exportada:\n{saved}")

        def _error(e):
            self.set_status("")
            QMessageBox.warning(self, "BAP", f"Falha ao exportar planilha:\n{e}")

        self._run_async(_work, on_done=_done, on_error=_error)

    def _on_theme_toggled(self, dark_mode: bool):
        theme = "dark" if dark_mode else "light"
        set_theme(theme)
        if self.config:
            self.config.set("theme", theme)
        qt_app = QApplication.instance()
        qt_app.setPalette(qpalette(get_palette(dark_mode)))
        qt_app.setStyleSheet(get_stylesheet())
        self.theme_changed.emit()

    def _run_async(self, fn, *, on_done, on_error=None):
        """Roda ``fn`` no DatabaseWorker; fallback síncrono antes do init."""
        from andaime.qt.db_runner import run_or_sync

        run_or_sync(
            getattr(self, "_db_runner", None),
            fn,
            on_done=on_done,
            on_error=on_error,
        )

    def init_backend(self):
        self.config = self._app.config
        self.db = self._app.db

        from andaime.db_worker import DatabaseWorker
        from andaime.qt.db_runner import DbAsyncRunner
        self._db_worker = DatabaseWorker(self.db)
        self._db_runner = DbAsyncRunner(self._db_worker)

        def _load():
            from bap.utils.arquivo_storage import resolve_arquivos_root
            from bap.utils.remessa_service import ensure_remessas

            root = resolve_arquivos_root(self.config.get_all())
            ensure_remessas(self.db, root)
            pacientes = self.db.get_all_pacientes()
            active = self._resolve_active_lote()
            return pacientes, active

        self._db_runner.run(_load, on_done=self._on_backend_loaded)

    def _on_backend_loaded(self, result) -> None:
        pacientes, active = result
        self._init_remessa_with(active)
        self._header.set_patients(pacientes)
        self._header.set_descricoes(self.db.get_distinct_descricoes())
        self._remessa_page.refresh(force=False)
        self._sender.scan_drs_messages()
        self.set_status("")

    def _init_remessa_with(self, active) -> None:
        self._doc_page.set_remessa_db(self.db)
        self._remessa_page.set_remessa_db(self.db)
        runner = getattr(self, "_db_runner", None)
        if runner is not None:
            self._remessa_page.set_async_runner(runner)
        self._sender.set_db(self.db)
        self._sender.set_config(self.config)
        self._remessa_page.set_config(self.config)
        if runner is not None:
            self._sender.set_async_runner(runner)
        self._sync_pages_remessa(active, emit=False)
        self._active_lote = active

    def _sync_pages_remessa(self, lote, emit: bool = False) -> None:
        self._doc_page.set_remessa_active(lote, emit=emit)
        self._remessa_page.set_remessa_active(lote, emit=emit)

    def _resolve_active_lote(self):
        lotes = self.db.get_all_lotes()
        if not lotes:
            return None
        # A remessa ativa é a mais recente por data.
        return lotes[0]

    def _grid_item_bytes(self, item: GridItem) -> bytes | None:
        """Lazy BLOB resolver for saved grid items (G3-B).

        Saved items carry only ``arquivo_id``; the PDF bytes are fetched from
        the DB on demand for thumbnail/preview and never retained in RAM.
        """
        if self.db is None:
            return None
        aid = item.arquivo_id
        if aid is None:
            return None
        return self.db.get_arquivo_conteudo(aid)

    def _on_remessa_changed(self, lote) -> None:
        # ``set_active`` atualiza o rótulo antes de emitir, então o lote
        # anterior não pode ser lido do rótulo; comparamos com o conhecido.
        prev = self._active_lote
        if self.config and lote is not None:
            current_last = self.config.get("last_lote_id")
            if current_last != lote.id:
                self.config.set("last_lote_id", lote.id)
        if lote is not None:
            self.set_status(f"Remessa ativa: {format_date_display(lote.date)}")
        self._sync_pages_remessa(lote, emit=False)
        self._active_lote = lote
        if prev is not None and lote is not None and prev.id == lote.id:
            # Mesma remessa (ex.: data editada ou re-seleção): apenas atualiza
            # o rótulo; não reinicia o contexto do cabeçalho nem a grade.
            self._remessa_page.refresh()
            return
        self._header.set_ciclo(1)
        self._remessa_page.refresh()
        if self._stack.currentWidget() is self._doc_page:
            self._sync_grid()

    def _on_patient_selected(self, paciente: Paciente | None) -> None:
        self._selected_patient_id = paciente.id if paciente is not None else None
        self._header.set_ciclo(1)
        self._sync_grid()

    def _current_processo(self) -> Processo | None:
        if self.db is None or self.config is None:
            return None
        if not self._header.nome:
            return None
        lote = self._remessa_label.active() or self._resolve_active_lote()
        if lote is None:
            return None
        paciente = self.db.find_paciente_by_name(self._header.nome)
        if paciente is None:
            return None
        procs = self.db.get_processos_by_context(
            paciente.id, lote.id, self._header.tipo, self._header.solicitacao
        )
        idx = self._header.ciclo - 1
        if 0 <= idx < len(procs):
            return procs[idx]
        return None

    def _on_ciclo_changed(self, _value: int) -> None:
        self._sync_grid()

    def _on_files_dropped(self, _count: int) -> None:
        """Ao arrastar arquivos para a grade sem processo salvo para o contexto,
        muda para a remessa mais recente (o novo processo vai para ela) e marca
        o status como "em análise" (processo em formação)."""
        if self._current_processo() is None:
            lote = self._resolve_active_lote()
            if lote is not None:
                self._sync_pages_remessa(lote, emit=True)
            # Não sobrescreve uma escolha explícita do operador: só aplica
            # "em análise" quando o seletor ainda está no valor padrão.
            if self._status_selector.status() in (NULL_STATUS, Status.EM_ANALISE):
                self._status_selector.set_status(Status.EM_ANALISE, emit=False)

    def _on_filtros_changed(self) -> None:
        self._header.set_ciclo(1)
        self._sync_grid()

    def _sync_grid(self, processo: Processo | None = None) -> None:
        # Durante o carregamento programático de um processo (open_processo),
        # os setters do cabeçalho emitem sinais que disparariam syncs parciais
        # (com contexto incompleto) e trocas de remessa indevidas. Suprimimos
        # esses syncs; open_processo faz um único sync final.
        if self._loading:
            return
        self._grid.set_doc_exclusions(
            RENOVACAO_DOC_EXCLUSIONS
            if self._header.solicitacao == "renovacao"
            else set()
        )
        if processo is None:
            processo = self._current_processo()
        if processo is None:
            # Regra única: só limpa a grade quando o sync anterior mostrava um
            # processo (processo -> nenhum). Se já não havia processo (nenhum ->
            # nenhum), preserva os arquivos montados manualmente na grade.
            if self._grid_showing_process:
                self._grid.set_items([])
                self._header.set_descricao("")
            # Sem processo: status é "Nenhum" por padrão, ou "em análise"
            # quando há documentos montados na grade (processo em formação).
            has_docs = len(self._grid.items()) > 0
            default_status = Status.EM_ANALISE if has_docs else NULL_STATUS
            # Não sobrescreve uma escolha explícita do operador: só aplica o
            # status padrão quando o seletor ainda está num valor padrão.
            if self._status_selector.status() in (NULL_STATUS, Status.EM_ANALISE):
                self._status_selector.set_status(default_status, emit=False)
            self._grid_showing_process = False
            self.set_status("Nenhum processo para este contexto.")
            return

        items = []
        if processo.is_archived:
            from bap.utils.arquivo_storage import resolve_arquivos_root
            from bap.utils.remessa_email import processo_pdf_path
            from andaime.pdf import page_count

            root = resolve_arquivos_root(self.config.get_all())
            pdf_path = processo_pdf_path(root, processo)
            arqs = self.db.get_arquivos_by_processo(processo.id)
            n_pages = page_count(pdf_path) if pdf_path.exists() else len(arqs)
            for i in range(n_pages):
                arq = arqs[i] if i < len(arqs) else None
                items.append(GridItem(
                    path=str(pdf_path),
                    page=i,
                    arquivo_id=arq.id if arq else None,
                    arquivo_original=arq.arquivo_original if arq else pdf_path.name,
                    tipo_documento=arq.tipo_documento if arq else "outro",
                ))
        else:
            for a in self.db.get_arquivos_by_processo(processo.id):
                items.append(GridItem(
                    page=0,
                    arquivo_id=a.id,
                    arquivo_original=a.arquivo_original,
                    tipo_documento=a.tipo_documento or "outro",
                ))
        n = len(items)
        arquivos = "1 arquivo" if n == 1 else f"{n} arquivos"
        self._grid.set_items(
            items,
            status_label=f"Carregando processo {processo.protocolo} - {arquivos}…",
        )
        self._header.set_descricao(processo.descricao or "")
        self._status_selector.set_status(processo.status, emit=False)
        self._grid_showing_process = True
        self.set_status(
            f"Processo {processo.protocolo} carregado. - {arquivos}"
        )

    def _on_status_changed(self, key: str, observacoes: str = "") -> None:
        processo = self._current_processo()
        if processo is None:
            # Processo ainda não existe: adia a observação para o Save.
            if observacoes:
                self._status_selector.pending_obs = observacoes
            return
        if processo.status != key:
            self.db.update_processo_status(
                processo.id, key, observacoes or None
            )
            self.set_status(
                f"Status alterado para '{status_display_label(key)}'."
            )
        elif observacoes:
            self.db.add_status_observation(processo.id, observacoes)

    def _on_salvar(self) -> None:
        if self.db is None or self.config is None:
            self.set_status("Backend não inicializado.", "status_error")
            return

        # Bloqueia Save concorrente (botão + Ctrl+S) e enquanto a grade monta
        # tiles: evita duplicar processo ou disparar com a grade pela metade.
        if self._grid.is_busy():
            return

        nome = self._header.nome
        if not nome:
            self.set_status(
                "Informe o nome do paciente antes de salvar.", "status_warning"
            )
            return

        if not self._header.solicitacao or not self._header.tipo:
            self.set_status(
                "Selecione o tipo de solicitação e o tipo antes de salvar.",
                "status_warning",
            )
            return

        lote = self._remessa_label.active() or self._resolve_active_lote()
        if lote is None:
            self.set_status("Nenhuma remessa disponível.", "status_error")
            return

        # Captura o estado da UI (barato) antes de sair da thread principal.
        telefone = normalize_phone(self._header.telefone)
        tipo = self._header.tipo
        solicitacao = self._header.solicitacao
        descricao = self._header.descricao
        status = self._status_selector.status()
        # Consome a observação pendente (digitada antes do processo existir).
        pending_obs = self._status_selector.pending_obs
        self._status_selector.pending_obs = ""

        processo = self._current_processo()
        processo_id = processo.id if processo is not None else None
        is_update = processo is not None

        # Reordena os widgets (thread principal) e tira um snapshot dos itens
        # da grade — o trabalho pesado (BLOBs, render) roda na thread do worker.
        self._grid.sort_by_doc_type()
        items_snapshot = [copy.copy(it) for it in self._grid.items()]

        # Trava a grade durante o Save: impede que drops/edições alterem a
        # ordem dos itens vivos e desalinhem o snapshot ao aplicar o resultado.
        self._grid.set_locked(True)
        self.set_status("Salvando…", "status_warning")
        self._run_async(
            lambda: self._salvar_work(
                nome, telefone, tipo, solicitacao, descricao, status,
                lote.id, processo_id, is_update, items_snapshot, pending_obs,
            ),
            on_done=lambda res: self._on_salvar_done(res, is_update),
            on_error=self._on_salvar_error,
        )

    def _on_salvar_error(self, e: BaseException) -> None:
        self._grid.set_locked(False)
        self.set_status(f"Falha ao salvar: {e}", "status_error")

    def _salvar_work(
        self,
        nome: str,
        telefone: str,
        tipo: str,
        solicitacao: str,
        descricao: str,
        status: str,
        lote_id: int,
        processo_id: int | None,
        is_update: bool,
        items: list[GridItem],
        pending_obs: str = "",
    ) -> dict:
        """Persiste o processo na thread do banco (fora da UI).

        Toda leitura/escrita de DB e toda codificação de PDF/BLOB acontece
        aqui; a thread principal só recebe o resultado em ``_on_salvar_done``.
        """
        paciente = self.db.find_paciente_by_name(nome)
        paciente_info = ""
        if paciente is None:
            paciente = self.db.create_paciente(nome, telefone)
            paciente_info = " (paciente novo)"
        elif telefone and telefone != (paciente.telefone or ""):
            self.db.update_paciente(paciente.id, telefone=telefone)
            paciente = self.db.get_paciente_by_id(paciente.id)
            paciente_info = " (paciente atualizado)"

        if processo_id is None:
            processo = self.db.create_processo(
                paciente_id=paciente.id,
                lote_id=lote_id,
                tipo=tipo,
                solicitacao=solicitacao,
                descricao=descricao,
            )
            processo_id = processo.id
        elif descricao and descricao != (
            self.db.get_processo_by_id(processo_id).descricao or ""
        ):
            self.db.update_processo(processo_id, descricao=descricao)

        # Persiste a mudança de status (com a observação pendente) ou, se o
        # status não mudou, registra a observação isolada — para não perdê-la.
        fresh = self.db.get_processo_by_id(processo_id)
        if status != NULL_STATUS and fresh is not None and fresh.status != status:
            self.db.update_processo_status(
                processo_id, status, observacoes=pending_obs or None
            )
        elif pending_obs:
            self.db.add_status_observation(processo_id, pending_obs)

        if fresh is not None and fresh.is_archived:
            self._salvar_work_archived(processo_id, fresh, items)
        else:
            self._salvar_work_active(processo_id, items)

        return {
            "processo_id": processo_id,
            "saved": len(items),
            "is_update": is_update,
            "paciente_info": paciente_info,
            "items": items,
        }

    def _salvar_work_archived(
        self, processo_id: int, fresh: Processo, items: list[GridItem]
    ) -> None:
        """Persiste um processo arquivado: metadados no DB, conteúdo no PDF."""
        from pathlib import Path

        import hashlib

        from andaime.pdf import merge_pdfs
        from bap.utils.arquivo_storage import resolve_arquivos_root
        from bap.utils.remessa_email import processo_pdf_path

        arqs = self.db.get_arquivos_by_processo(processo_id)
        existing = {a.id: a for a in arqs}
        seen: set[int] = set()

        # Metadados (criação/atualização/remoção de arquivos) em uma única
        # transação: atômico e um só commit. A montagem do PDF fica fora —
        # é I/O de disco e não deve segurar um write lock no banco.
        with self.db.transaction():
            for ordem, item in enumerate(items, start=1):
                aid = item.arquivo_id
                if aid is not None and aid in existing:
                    seen.add(aid)
                    existing_doc = existing[aid]
                    item_tipo = item.tipo_documento
                    if existing_doc.ordem != ordem or existing_doc.tipo_documento != item_tipo:
                        self.db.update_arquivo(
                            aid, ordem=ordem, tipo_documento=item_tipo,
                        )
                    continue
                original = item.display_name
                arq = self.db.create_arquivo(
                    processo_id=processo_id,
                    tipo_documento=item.tipo_documento,
                    conteudo=None,
                    arquivo_original=original,
                    ordem=ordem,
                )
                item.arquivo_id = arq.id

            for aid in existing:
                if aid not in seen:
                    self.db.delete_arquivo(aid)

        root = resolve_arquivos_root(self.config.get_all())
        pdf_path = processo_pdf_path(root, fresh)
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        conteudos = []
        for item in items:
            pdf_bytes = item.to_pdf_bytes()
            if pdf_bytes is not None:
                conteudos.append(pdf_bytes)
        if conteudos:
            merge_pdfs(conteudos, str(pdf_path))
            pdf_sig = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
            self.db.set_processo_pdf_sig(processo_id, pdf_sig)
            for i, item in enumerate(items):
                item.path = str(pdf_path)
                item.page = i
                item.data = None

    def _salvar_work_active(
        self, processo_id: int, items: list[GridItem]
    ) -> None:
        """Persiste um processo ativo: BLOBs no banco."""
        arqs = self.db.get_arquivos_by_processo(processo_id)
        existing = {a.id: a for a in arqs}
        seen: set[int] = set()

        # Toda a mutação de metadados + BLOBs em uma única transação:
        # atômica e um só commit (commits individuais são caros em rede).
        with self.db.transaction():
            for ordem, item in enumerate(items, start=1):
                aid = item.arquivo_id
                if aid is not None and aid in existing:
                    # Já salvo: atualiza ordem e tipo_documento se mudaram.
                    seen.add(aid)
                    existing_doc = existing[aid]
                    item_tipo = item.tipo_documento
                    if existing_doc.ordem != ordem or existing_doc.tipo_documento != item_tipo:
                        self.db.update_arquivo(
                            aid, ordem=ordem, tipo_documento=item_tipo,
                        )
                    # Conteúdo pode ter mudado (ex.: rotação da página) —
                    # re-grava o BLOB para que o PDF exportado reflita isso.
                    if item.data is not None:
                        self.db.update_arquivo_conteudo(aid, item.data)
                    continue
                # Novo item: converte para PDF de página única e grava o BLOB.
                conteudo = item.to_pdf_bytes()
                original = item.display_name
                arq = self.db.create_arquivo(
                    processo_id=processo_id,
                    tipo_documento=item.tipo_documento,
                    conteudo=conteudo,
                    arquivo_original=original,
                    ordem=ordem,
                )
                item.arquivo_id = arq.id
                item.page = 0
                item.data = None
                item.path = None

            for aid in existing:
                if aid not in seen:
                    self.db.delete_arquivo(aid)

    def _on_salvar_done(self, res: dict | None, is_update: bool) -> None:
        # Destrava a grade travada no início do Save (ver ``_on_salvar``).
        self._grid.set_locked(False)
        if res is None:
            return

        # Aplica o estado persistido de volta aos itens vivos da grade (em
        # ordem) — sem recriar tiles nem re-renderizar thumbnails, já que a
        # grade já exibe exatamente o que o usuário vê. A grade ficou travada
        # durante o Save, então a ordem dos itens vivos casa com o snapshot.
        live_items = self._grid.items()
        for live, saved in zip(live_items, res["items"]):
            live.__dict__.update(saved.__dict__)

        self._grid_showing_process = True
        # Mantém a lista de pacientes/descrições do cabeçalho em dia (um
        # paciente novo/atualizado precisa aparecer na busca).
        self._header.set_patients(self.db.get_all_pacientes())
        self._header.set_descricoes(self.db.get_distinct_descricoes())

        fresh = self.db.get_processo_by_id(res["processo_id"])
        protocolo = fresh.protocolo if fresh is not None else ""
        # O save alterou o banco (status, descrição, paciente, arquivos ou um
        # processo novo): atualiza a tabela de remessas para refletir o estado.
        self._remessa_page.refresh()
        self.set_status(
            f"Processo {protocolo} "
            f"{'atualizado' if res['is_update'] else 'salvo'}{res['paciente_info']} — "
            f"{res['saved']} {'arquivo' if res['saved'] == 1 else 'arquivos'}",
            "status_success",
        )

    def navigate_to(self, page_name: str):
        if page_name == "remessas":
            self._stack.setCurrentWidget(self._remessa_page)
        elif page_name == "document":
            self._stack.setCurrentWidget(self._doc_page)

    def open_processo(self, processo_id: int) -> None:
        if self.db is None:
            return
        processo = self.db.get_processo_by_id(processo_id)
        if processo is None:
            return

        # Processos "incompleto" ou "em_analise" avançam para a remessa mais
        # recente ao serem carregados na página de documentos — exceto processos
        # arquivados, que permanecem no lote histórico.
        if not processo.is_archived and processo.status in (Status.INCOMPLETO, Status.EM_ANALISE):
            latest = self._resolve_active_lote()
            if latest is not None and latest.id != processo.lote_id:
                reassigned = self.db.reassign_processo_lote(
                    processo.id, latest.id
                )
                if reassigned is not None:
                    processo = reassigned

        lote = self.db.get_lote_by_id(processo.lote_id)

        # Carrega o contexto de forma atômica: os setters abaixo emitem sinais
        # (paciente/ciclo) que dispariam syncs parciais; suprimimos até o fim.
        self._loading = True
        try:
            if lote is not None:
                self._sync_pages_remessa(lote, emit=False)
                self._on_remessa_changed(lote)

            paciente = (
                self.db.get_paciente_by_id(processo.paciente_id)
                if processo.paciente_id
                else None
            )
            if paciente is not None:
                self._header.set_paciente_by_id(paciente)
                self._selected_patient_id = paciente.id
            self._header.set_tipo(processo.tipo)
            self._header.set_solicitacao(processo.solicitacao)

            if paciente is not None and lote is not None:
                contextos = self.db.get_processos_by_context(
                    paciente.id, lote.id, processo.tipo, processo.solicitacao
                )
                idx = next(
                    (i for i, p in enumerate(contextos) if p.id == processo.id), 0
                )
                self._header.set_ciclo(idx + 1)
            else:
                self._header.set_ciclo(1)

            self._header.set_descricao(processo.descricao)
        finally:
            self._loading = False

        # Limpa a grade e navega ANTES de montar a nova: a página de documentos
        # aparece vazia imediatamente (sem mostrar as tiles do processo
        # anterior) e a construção incremental das novas tiles (uma a uma, com
        # a UI livre entre passos) é vista pelo usuário em vez de travar a
        # página de remessas até terminar.
        self._grid.clear()
        self.navigate_to("document")
        # Força o repaint da grade vazia antes de começar a montagem síncrona
        # das novas tiles; sem isso o Qt só repinta ao final e a grade antiga
        # "pisca" até a nova ficar pronta.
        QApplication.processEvents()
        self._sync_grid(processo)

    def shutdown_backend(self):
        active = self._remessa_label.active()
        if self.config and active is not None:
            self.config.set("last_lote_id", active.id)
        # wait=False: o worker pode estar em I/O de rede (scan DRS / Gmail);
        # aguardar congelaria a janela. O close do banco roda no atexit.
        worker = getattr(self, "_db_worker", None)
        if worker is not None:
            try:
                worker.shutdown(wait=False)
            except Exception:  # pragma: no cover - defensivo
                pass

    def closeEvent(self, event):
        self.shutdown_backend()
        super().closeEvent(event)
