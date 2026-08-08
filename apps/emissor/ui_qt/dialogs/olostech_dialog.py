#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Olostech Registration Dialog — coletar tipos de receita e registrar."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

ACTION_LABELS = {
    2: "Receita Simples",
    4: "Receita Especial",
    6: "Notificacao B",
    7: "Notificacao A",
    9: "Notificacao Talidomida",
}
NOTIFICATION_ACTIONS = {6, 7, 9}


class RegistrationWorker(QThread):
    """Worker thread para registro Olostech."""

    finished_with_result = Signal(bool, str)

    def __init__(
        self,
        olostech_cfg: dict[str, Any],
        patient_sus: str,
        professional_code: str,
        items: list[dict[str, Any]],
    ) -> None:
        super().__init__()
        self.olostech_cfg = olostech_cfg
        self.patient_sus = patient_sus
        self.professional_code = professional_code
        self.items = items

    def run(self) -> None:
        try:
            from emissor.olostech.auth import OlostechAuth
            from emissor.olostech.dispensing import Dispensing

            # Converte OlostechConfig para dict se necessário
            cfg = self.olostech_cfg
            if hasattr(cfg, "to_dict"):
                cfg = cfg.to_dict()

            auth = OlostechAuth(cfg)
            if not auth.machine_auth():
                self.finished_with_result.emit(
                    False, "Falha na autenticacao de maquina"
                )
                return
            if not auth.user_login():
                self.finished_with_result.emit(False, "Falha no login")
                return
            disp = Dispensing(auth)
            success = disp.dispense_retirada(
                patient_sus=self.patient_sus,
                professional_code=self.professional_code,
                items=self.items,
            )
            if success:
                self.finished_with_result.emit(True, "Registrado com sucesso")
            else:
                self.finished_with_result.emit(
                    False, "Falha na dispensacao — ver detalhes no log"
                )
        except Exception as e:
            self.finished_with_result.emit(False, f"Erro: {e}")


def show_olostech_dialog(
    parent: QWidget,
    retirada: Any,
    patient: Any,
    olostech_cfg: dict[str, Any],
) -> tuple[bool, str] | None:
    """Abre dialogo para coletar tipo de receita por item e registrar.

    Args:
        parent: Janela pai.
        retirada: Retirada atual (com itens).
        patient: Paciente selecionado.
        olostech_cfg: Configuracao Olostech.

    Returns:
        Tuple (sucesso, mensagem) ao finalizar, ou None se cancelado.
    """
    dialog = QDialog(parent)
    dialog.setWindowTitle("Registrar Olostech")
    dialog.setMinimumWidth(500)

    layout = QVBoxLayout(dialog)
    layout.setSpacing(12)

    # Info do paciente
    patient_name = getattr(patient, "nome", "?") or "?"
    info = QLabel(f"Paciente: {patient_name}")
    info.setStyleSheet("font-weight: bold;")
    layout.addWidget(info)

    # Itens
    form = QFormLayout()
    form.setSpacing(8)

    combos: dict[int, QComboBox] = {}
    notif_edits: dict[int, QLineEdit] = {}

    items = getattr(retirada, "itens", []) or []
    for idx, item in enumerate(items):
        descricao = getattr(item, "descricao", "") or ""
        quantidade = getattr(item, "quantidade", "") or ""

        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)

        label = QLabel(f"{descricao}  x{quantidade}")
        label.setMinimumWidth(200)
        row_layout.addWidget(label)

        combo = QComboBox()
        combo.setMaximumWidth(180)
        for action_id, action_label in ACTION_LABELS.items():
            combo.addItem(action_label, action_id)
        row_layout.addWidget(combo)
        combos[idx] = combo

        notif_edit = QLineEdit()
        notif_edit.setPlaceholderText("Nr. Notificacao")
        notif_edit.setEnabled(False)
        notif_edit.setMaximumWidth(120)
        row_layout.addWidget(notif_edit)
        notif_edits[idx] = notif_edit

        def _on_change(_idx: int, c: QComboBox = combo, e: QLineEdit = notif_edit) -> None:
            e.setEnabled(c.currentData() in NOTIFICATION_ACTIONS)

        combo.currentIndexChanged.connect(_on_change)

        form.addRow(row_widget)

    layout.addLayout(form)

    # Progress bar (hidden initially)
    progress = QProgressBar()
    progress.setRange(0, 0)
    progress.setVisible(False)
    layout.addWidget(progress)

    # Status label
    status_label = QLabel("")
    status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    status_label.setVisible(False)
    layout.addWidget(status_label)

    # Botoes
    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    layout.addWidget(buttons)

    result: tuple[bool, str] | None = None
    worker: RegistrationWorker | None = None

    def _collect_items() -> list[dict[str, Any]]:
        collected = []
        for idx, item in enumerate(items):
            action_type = combos[idx].currentData()
            notif_nr = notif_edits[idx].text().strip() if action_type in NOTIFICATION_ACTIONS else ""
            collected.append({
                "material_code": getattr(item, "item_id", "") or "",
                "material_desc": getattr(item, "descricao", "") or "",
                "quantity": int(getattr(item, "quantidade", 0) or 0),
                "action_type": action_type,
                "notificacao_nr": notif_nr,
                "dias": int(getattr(item, "dias", 0) or 0),
            })
        return collected

    def _on_accepted() -> None:
        nonlocal result, worker

        # Coletar dados
        collected = _collect_items()
        if not collected:
            return

        # Validar configuracao
        if not _cfg_value(olostech_cfg, "username") or not _cfg_value(olostech_cfg, "password"):
            status_label.setText("Configure usuario e senha do Olostech")
            status_label.setStyleSheet("color: red;")
            status_label.setVisible(True)
            return

        # Desabilitar controles, mostrar progresso
        for c in combos.values():
            c.setEnabled(False)
        for e in notif_edits.values():
            e.setEnabled(False)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setEnabled(False)
        progress.setVisible(True)
        status_label.setText("Registrando...")
        status_label.setStyleSheet("")
        status_label.setVisible(True)

        # Executar em background
        patient_sus = matricula_str(patient)
        professional_code = str(getattr(patient, "crm", "") or "")

        worker = RegistrationWorker(
            olostech_cfg=olostech_cfg,
            patient_sus=patient_sus,
            professional_code=professional_code,
            items=collected,
        )
        worker.finished_with_result.connect(_on_finished)
        worker.start()

    def _on_finished(success: bool, message: str) -> None:
        nonlocal result
        result = (success, message)
        progress.setVisible(False)
        status_label.setText(message)
        status_label.setStyleSheet(
            "color: green;" if success else "color: red;"
        )
        # Substituir botoes: apenas Fechar
        buttons.setStandardButtons(QDialogButtonBox.StandardButton.Close)
        try:
            buttons.accepted.disconnect(_on_accepted)
        except RuntimeError:
            pass
        buttons.button(QDialogButtonBox.StandardButton.Close).clicked.connect(dialog.accept)

    buttons.accepted.connect(_on_accepted)
    buttons.rejected.connect(dialog.reject)

    dialog.exec()
    return result


def _cfg_value(cfg: dict[str, Any] | Any, key: str) -> str:
    """Obtém valor da configuração (aceita dict ou OlostechConfig dataclass)."""
    if isinstance(cfg, dict):
        return str(cfg.get(key, "") or "")
    return str(getattr(cfg, key, "") or "")


def matricula_str(patient: Any) -> str:
    """Obtem matricula/SUS do paciente como string."""
    for attr in ("matricula", "sus", "id"):
        val = getattr(patient, attr, None)
        if val is not None:
            return str(val)
    return "?"
