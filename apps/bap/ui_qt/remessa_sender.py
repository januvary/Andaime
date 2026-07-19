"""Orquestra o envio de remessas via Gmail (rascunhos + Drive).

``RemessaSender`` é um ``QObject`` que centraliza todo o fluxo de envio de
remessas: montagem dos PDFs combinados, autenticação OAuth, criação de
rascunhos no Gmail, verificação de rascunhos pendentes e varredura de
mensagens DRS. O trabalho pesado roda em ``_EnviarRemessaWorker`` (QThread);
a UI (diálogos de autorização/confirmação) é gerenciada aqui, na thread
principal do Qt.

Sinais emitidos para a ``MainWindow``:
- ``status_changed(text, color)`` — atualiza a linha de status das páginas.
- ``info(text)`` / ``warn(text)`` — exibe caixa de mensagem informativa/aviso.
- ``remessas_changed()`` — pede refresh da tabela de remessas.
- ``atulizacoes_changed()`` — pede atualização do contador de atualizações DRS.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from bap.constants import SOLICITACAO_LABELS, Status
from bap.utils.date_utils import format_date_display
from bap.ui_qt.widgets.dialogs import scaffold_dialog, make_dialog_button_row, confirm_dialog


def _gmail_service(cfg):
    """Obtém um serviço Gmail não-interativo a partir da configuração."""
    from bap.utils import gmail_client

    return gmail_client.get_service(
        cfg.gmail_credentials_path,
        cfg.gmail_token_path,
    )


class _EnviarRemessaWorker(QThread):
    """Monta os PDFs combinados + autentica no Gmail + cria rascunhos (off-thread).

    A montagem dos grupos (leitura de BLOBs + merge de PDFs), que travaria a
    GUI se feita na thread principal, roda aqui. Emite ``auth_needed`` (com a
    URL de autorização) quando é necessário consentimento interativo. Nenhuma
    escrita no banco é feita aqui — o resultado é devolvido para a GUI, que
    persiste os ``pending_sends``.
    """

    auth_needed = Signal(str)
    done = Signal(object)  # list[(RemessaGroup, DraftResult)]
    failed = Signal(str)

    def __init__(self, cfg, lote, db, parent=None):
        super().__init__(parent)
        self._cfg = cfg
        self._lote = lote
        self._db = db
        self._handle = None

    def cancel(self) -> None:
        handle = self._handle
        if handle is not None:
            handle.cancel()

    def _obtain_creds(self, cfg):
        """Resolve as credenciais OAuth, disparando o fluxo interativo se preciso.

        Retorna ``(service, creds)`` ou levanta ``GmailError``.
        """
        from bap.utils import gmail_client
        from bap.utils.gmail_client import GmailError
        from google.oauth2.credentials import Credentials

        try:
            service = _gmail_service(cfg)
            tok_path = gmail_client.resolve_token_path(cfg.gmail_token_path)
            creds = None
            if tok_path.exists():
                creds = Credentials.from_authorized_user_file(
                    str(tok_path), gmail_client.SCOPES
                )
        except GmailError:
            handle = gmail_client.start_auth_flow(
                cfg.gmail_credentials_path, cfg.gmail_token_path
            )
            self._handle = handle
            self.auth_needed.emit(handle.auth_url)
            creds = handle.wait(timeout_seconds=300)
            service = gmail_client.service_from_credentials(creds)
        return service, creds

    def _create_drafts(self, service, creds, groups, cfg) -> list:
        """Cria rascunhos no Gmail para cada grupo da remessa."""
        from bap.utils import gmail_client

        results = []
        for g in groups:
            res = gmail_client.create_draft(
                service,
                g.to_email,
                g.subject,
                g.html_body,
                g.attachments,
                sender=cfg.operator_email,
                creds=creds,
                drive_folder=g.drive_folder,
            )
            results.append((g, res))
        return results

    def run(self) -> None:  # noqa: D401 - QThread entrypoint
        from bap.utils import gmail_client
        from bap.utils.gmail_client import GmailError, GmailAuthRequired
        from bap.utils.remessa_email import build_remessa_groups

        cfg = self._cfg
        try:
            # Monta os grupos (leitura de BLOBs + merge de PDFs) fora da thread
            # da GUI para não congelar a interface durante o envio.
            groups = build_remessa_groups(self._db, cfg, self._lote)
            if not groups:
                self.failed.emit(
                    "Nenhum processo 'completo' nesta remessa para enviar."
                )
                return

            service, creds = self._obtain_creds(cfg)
            if creds is None:
                self.failed.emit(
                    "Credenciais Gmail indisponíveis para anexar via Drive."
                )
                return

            try:
                results = self._create_drafts(service, creds, groups, cfg)
            except GmailAuthRequired:
                # Token existe mas não tem escopos suficientes (ex.: falta
                # drive.file após ampliação dos escopos). Apaga o token
                # obsoleto e repete o fluxo de consentimento, depois tenta
                # novamente uma vez.
                gmail_client.resolve_token_path(
                    cfg.gmail_token_path
                ).unlink(missing_ok=True)
                service, creds = self._obtain_creds(cfg)
                if creds is None:
                    self.failed.emit(
                        "Credenciais Gmail indisponíveis para anexar via Drive."
                    )
                    return
                results = self._create_drafts(service, creds, groups, cfg)
        except GmailError as e:
            self.failed.emit(str(e))
            return
        except Exception as e:  # pragma: no cover - defensivo
            self.failed.emit(f"Falha ao criar rascunho(s): {e}")
            return

        self.done.emit(results)


class RemessaSender(QObject):
    """Controla o envio de remessas, verificação de pendentes e scan DRS.

    Instanciado pela ``MainWindow`` com o widget pai (para diálogos). DB,
    config e async runner são injetados via setters quando o backend inicializa.
    """

    status_changed = Signal(str, object)  # (text, color_key | None)
    info = Signal(str)
    warn = Signal(str)
    remessas_changed = Signal()
    atualizacoes_changed = Signal()

    def __init__(self, parent_widget):
        super().__init__()
        self._parent = parent_widget
        self._db = None
        self._config = None
        self._runner = None
        self._enviar_worker: _EnviarRemessaWorker | None = None
        self._enviar_lote = None
        self._auth_dialog: QDialog | None = None

    # ========== Dependency injection ==========

    def set_db(self, db) -> None:
        self._db = db

    def set_config(self, config) -> None:
        self._config = config

    def set_async_runner(self, runner) -> None:
        self._runner = runner

    # ========== UI feedback (thin wrappers over signals) ==========

    def _info(self, text: str) -> None:
        self.info.emit(text)

    def _warn(self, text: str) -> None:
        self.warn.emit(text)

    def set_status(self, text: str, color: str | None = None) -> None:
        self.status_changed.emit(text, color)

    def _run_async(self, fn, *, on_done, on_error=None):
        """Roda ``fn`` no async runner; fallback síncrono antes do init."""
        from andaime.qt.db_runner import run_or_sync

        run_or_sync(self._runner, fn, on_done=on_done, on_error=on_error)

    # ========== Envio de remessa ==========

    def _prompt_missing_drs_emails(self, missing) -> bool:
        """Pede os e-mails do DRS ausentes e os salva na configuração.

        ``missing`` é a lista de ``(grupo, key)`` sem ``to_email``. Retorna
        ``True`` se todos os e-mails foram informados e salvos, ``False`` se o
        usuário cancelou.
        """
        if self._config is None:
            return False

        dlg, layout = scaffold_dialog(
            self._parent, "BAP — Configurar e-mail do DRS", spacing=12, min_width=420
        )
        intro = QLabel(
            "Informe o e-mail do DRS para enviar a(s) remessa(s) abaixo. "
            "O e-mail será salvo para os próximos envios."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        layout.addSpacing(4)

        edits: list[tuple[str, QLineEdit]] = []
        for grupo, key in missing:
            label = SOLICITACAO_LABELS.get(grupo, grupo)
            layout.addWidget(QLabel(f"{label}:"))
            edit = QLineEdit()
            edit.setPlaceholderText("email@drs.sp.gov.br")
            layout.addWidget(edit)
            edits.append((key, edit))

        layout.addSpacing(4)
        btn_row, [cancel, confirm] = make_dialog_button_row([
            ("Cancelar", "flat-fill"),
            ("Salvar", "primary"),
        ])
        cancel.clicked.connect(dlg.reject)
        confirm.clicked.connect(dlg.accept)
        layout.addLayout(btn_row)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return False

        values: list[tuple[str, str]] = []
        for key, edit in edits:
            email = edit.text().strip()
            if not email:
                self._warn("Todos os e-mails são obrigatórios para enviar.")
                return False
            values.append((key, email))

        for key, email in values:
            self._config.set(key, email)
        return True

    def enviar(self, lote) -> None:
        """Inicia o envio da remessa ``lote``: confirma, monta e cria rascunhos."""
        if self._db is None or self._config is None:
            return

        if self._enviar_worker is not None:
            self._info("Já existe um envio em andamento.")
            return

        cfg = self._config.get_all()

        # Solicita os e-mails do DRS (se faltarem) ANTES de montar os grupos,
        # para não reconstruir os PDFs combinados só para descobrir o que falta.
        from bap.utils.remessa_email import missing_drs_emails

        faltando = missing_drs_emails(self._db, cfg, lote)
        if faltando:
            if not self._prompt_missing_drs_emails(faltando):
                return
            cfg = self._config.get_all()

        # Contagem leve (sem ler BLOBs) para o diálogo de confirmação; a
        # montagem pesada dos PDFs combinados acontece no worker (off-thread).
        completos = self._db.get_processos_by_lote_and_status(
            lote.id, Status.COMPLETO
        )
        if not completos:
            self._info("Nenhum processo 'completo' nesta remessa para enviar.")
            return

        renovacoes = sum(1 for p in completos if p.solicitacao == "renovacao")
        primeiras = sum(1 for p in completos if p.solicitacao == "primeira")
        total = len(completos)
        lines = []
        if renovacoes:
            lines.append(
                f"- {SOLICITACAO_LABELS['renovacao']}: {renovacoes} processo(s)"
            )
        if primeiras:
            lines.append(
                f"- {SOLICITACAO_LABELS['primeira']}: {primeiras} processo(s)"
            )

        message = (
            f"Confirmar envio de {total} processo(s) da remessa de "
            f"{format_date_display(lote.date)}?\n\n"
            + "\n".join(lines)
            + "\n\nSerão criados rascunhos no Gmail para revisão."
        )
        if not confirm_dialog(
            self._parent,
            "BAP — Enviar Remessa",
            message,
            confirm_label="Confirmar",
            min_width=420,
        ):
            return

        self._enviar_lote = lote
        worker = _EnviarRemessaWorker(cfg, lote, self._db, self)
        self._enviar_worker = worker
        worker.auth_needed.connect(self._on_enviar_auth_needed)
        worker.done.connect(self._on_enviar_done)
        worker.failed.connect(self._on_enviar_failed)
        worker.finished.connect(self._on_enviar_thread_finished)
        self.set_status("Preparando remessa…", "status_warning")
        worker.start()

    def _on_enviar_auth_needed(self, url: str) -> None:
        self._close_auth_dialog()
        self._show_auth_dialog(url)

    def _on_enviar_done(self, results) -> None:
        self._close_auth_dialog()
        from bap.utils import gmail_client

        lote = self._enviar_lote
        if self._db is None or lote is None:
            return

        created = []
        urls: list[str] = []
        for g, res in results:
            self._db.create_pending_send(
                lote_id=lote.id,
                grupo=g.grupo,
                processo_ids=g.included_ids,
                draft_id=res.draft_id,
                message_id=res.message_id,
                rfc822_msgid=res.rfc822_msgid,
                to_email=g.to_email,
                subject=g.subject,
            )
            created.append(g)
            urls.append(gmail_client.draft_web_url(res.message_id))

        import webbrowser

        for url in urls:
            try:
                webbrowser.open(url)
            except Exception:  # pragma: no cover - ambiente sem navegador
                pass

        lines = []
        for g in created:
            skipped = (
                f", {len(g.skipped_ids)} sem documentos (ignorados)"
                if g.skipped_ids
                else ""
            )
            lines.append(
                f"- {g.label}: {len(g.included_ids)} processo(s){skipped} → {g.to_email}"
            )
        self._info(
            "Rascunho(s) criado(s) no Gmail:\n\n"
            + "\n".join(lines)
            + "\n\nRevise e clique em Enviar no Gmail. A remessa será marcada "
            "como enviada automaticamente quando o envio for detectado."
        )
        self.set_status("Rascunho(s) criado(s) no Gmail.", "status_success")
        self.remessas_changed.emit()

    def _on_enviar_failed(self, msg: str) -> None:
        self._close_auth_dialog()
        self.set_status("Falha ao enviar remessa.", "status_error")
        self._warn(msg)

    def _on_enviar_thread_finished(self) -> None:
        self._enviar_worker = None

    def _show_auth_dialog(self, url: str) -> None:
        dlg = QDialog(self._parent)
        dlg.setWindowTitle("Autorizar acesso ao Gmail")
        layout = QVBoxLayout(dlg)
        label = QLabel(
            "Abra o link abaixo no navegador e autorize o acesso ao Gmail.\n"
            "Após autorizar, o envio continua automaticamente."
        )
        label.setWordWrap(True)
        layout.addWidget(label)

        edit = QLineEdit(url)
        edit.setReadOnly(True)
        edit.setMinimumWidth(520)
        edit.setCursorPosition(0)
        layout.addWidget(edit)

        row = QHBoxLayout()
        btn_open = QPushButton("Abrir no navegador")
        btn_copy = QPushButton("Copiar link")
        row.addWidget(btn_open)
        row.addWidget(btn_copy)
        row.addStretch(1)
        layout.addLayout(row)

        def _open() -> None:
            import webbrowser

            try:
                webbrowser.open(url)
            except Exception:  # pragma: no cover - ambiente sem navegador
                pass

        def _copy() -> None:
            QApplication.clipboard().setText(url)
            self.set_status("Link de autorização copiado.", "toast_info_fg")

        btn_open.clicked.connect(_open)
        btn_copy.clicked.connect(_copy)
        dlg.rejected.connect(self._cancel_enviar)

        self._auth_dialog = dlg
        dlg.setModal(False)
        dlg.show()
        _open()

    def _close_auth_dialog(self) -> None:
        dlg = self._auth_dialog
        if dlg is not None:
            try:
                dlg.rejected.disconnect(self._cancel_enviar)
            except (RuntimeError, TypeError):
                pass
            dlg.close()
            self._auth_dialog = None

    def _cancel_enviar(self) -> None:
        worker = self._enviar_worker
        if worker is not None:
            worker.cancel()
        self.set_status("Autorização do Gmail cancelada.", "toast_info_fg")

    # ========== Verificação de rascunhos pendentes ==========

    def check_pending_sends(self) -> None:
        """Verifica rascunhos pendentes e finaliza os que já foram enviados.

        Silencioso: se não houver token do Gmail ou nada pendente, não faz nada.
        A parte DB/rede roda no async runner; a UI é atualizada no callback
        ``_on_pending_sends_done`` (thread principal do Qt).
        """
        if self._db is None or self._config is None:
            return

        def _work():
            pendings = self._db.get_pending_sends("pending")
            if not pendings:
                return 0

            cfg = self._config.get_all()
            from bap.utils import gmail_client
            from bap.utils.gmail_client import GmailError

            try:
                service = _gmail_service(cfg)
            except GmailError:
                return 0

            finalized = 0
            affected_lotes: set[int] = set()
            for ps in pendings:
                draft_id = ps.get("draft_id")
                if not draft_id:
                    continue
                try:
                    labels = gmail_client.get_draft_message_labels(
                        service, draft_id
                    )
                except gmail_client.GmailError:
                    continue
                if labels is None:
                    self._db.resolve_pending_send(ps["id"], "discarded")
                    continue
                if "SENT" in labels:
                    for pid in ps["processo_ids"]:
                        self._db.update_processo_status(pid, Status.ENVIADO)
                    self._db.resolve_pending_send(ps["id"], "sent")
                    finalized += 1
                    affected_lotes.add(ps["lote_id"])

            for lote_id in affected_lotes:
                self._finalize_lote_if_complete(lote_id)

            return finalized

        def _done(finalized):
            if finalized:
                self.set_status(
                    f"{finalized} envio(s) confirmado(s): processos marcados como enviados.",
                    "status_success",
                )
                self.remessas_changed.emit()

        self._run_async(_work, on_done=_done)

    def scan_drs_messages(self) -> None:
        """Escaneia e-mails do Gmail em busca de menções a pacientes.

        A varredura (rede + DB) roda no async runner; a contagem de
        atualizações é atualizada na thread principal, antes e depois.
        """
        if self._db is None or self._config is None:
            return
        self.atualizacoes_changed.emit()

        def _work():
            cfg = self._config.get_all()
            from bap.utils.gmail_client import GmailError

            try:
                service = _gmail_service(cfg)
            except GmailError:
                return
            from bap.utils.gmail_scanner import scan_drs_messages

            scan_drs_messages(self._db, service)

        def _done(_result):
            self.atualizacoes_changed.emit()

        self._run_async(_work, on_done=_done)

    def _finalize_lote_if_complete(self, lote_id: int) -> None:
        """Marca a remessa como enviada e abre a próxima quando não há mais
        rascunhos pendentes para ela."""
        remaining = [
            ps
            for ps in self._db.get_pending_sends("pending")
            if ps["lote_id"] == lote_id
        ]
        if remaining:
            return
        self._db.mark_lote_sent(lote_id)
        from bap.utils.remessa_service import ensure_next_open_lote

        ensure_next_open_lote(self._db)
