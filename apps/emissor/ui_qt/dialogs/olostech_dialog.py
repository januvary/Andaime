#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Olostech Registration Dialog — coletar tipos de receita e registrar."""

from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QThread, Signal
from dataclasses import dataclass
from emissor.database.models import Patient, Retirada
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from andaime.qt.dialogs import make_dialog_button_row, scaffold_dialog

ACTION_LABELS = {
    2: "Receita Simples",
    4: "Receita Especial",
    6: "Notificacao B",
    7: "Notificacao A",
    9: "Notificacao Talidomida",
}
NOTIFICATION_ACTIONS = {6, 7}  # Notif B/A exigem numero; Talidomida nao


@dataclass
class _ItemRow:
    """Uma linha do dialogo: item + combo de tipo + numero + codigo."""

    item: Any
    combo: QComboBox
    notif_edit: QLineEdit
    olostech_code: str


class NoScrollComboBox(QComboBox):
    """Combo que ignora o scroll: rola o dialogo em vez de trocar a selecao."""

    def wheelEvent(self, event) -> None:  # noqa: N802
        event.ignore()


def ask_notificacao(
    parent: QWidget, descricao: str, suggested_action: int
) -> tuple[int, str] | None:
    """Popup p/ item de notificacao sem numero (so B/A).

    Returns (action_type, numero) ou None se cancelado/sem numero.
    """
    dlg, layout = scaffold_dialog(
        parent, "Notificação controlada", min_width=380
    )

    info = QLabel(
        "O Olostech exige notificação para:\n"
        f"{descricao}\nConfirme o tipo e informe o número."
    )
    info.setWordWrap(True)
    layout.addWidget(info)

    combo = QComboBox()
    for action_id in (6, 7):
        combo.addItem(ACTION_LABELS[action_id], action_id)
    combo.setCurrentIndex(combo.findData(suggested_action))
    layout.addWidget(combo)

    edit = QLineEdit()
    edit.setPlaceholderText("Nr. Notificacao")
    edit.setMaxLength(60)
    layout.addWidget(edit)

    row, (cancel_btn, ok_btn) = make_dialog_button_row(
        [("Cancelar", "flat"), ("Confirmar", "primary")]
    )
    layout.addLayout(row)

    ok_btn.clicked.connect(dlg.accept)
    cancel_btn.clicked.connect(dlg.reject)

    if dlg.exec() != dlg.DialogCode.Accepted:
        return None
    number = edit.text().strip()
    if not number:
        return None
    return (combo.currentData(), number)


# Tipo inicial enviado ao servidor; o proprio Olostech detecta e ajusta
# o tipo de receita por material (_detect_action_type).
DEFAULT_ACTION_TYPE = 2  # Receita Simples


def merge_olostech_entries(
    entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Mescla entradas de mesmo material+tipo (soma qtde, maior dias).

    O servidor rejeita material duplicado ("Material já entregue...").
    """
    merged: dict[tuple[str, int], dict[str, Any]] = {}
    for e in entries:
        key = (e["material_code"], e["action_type"])
        if key in merged:
            merged[key]["quantity"] += e["quantity"]
            if e["dias"] > merged[key].get("dias", 0):
                merged[key]["dias"] = e["dias"]
            if not merged[key].get("notificacao_nr") and e["notificacao_nr"]:
                merged[key]["notificacao_nr"] = e["notificacao_nr"]
            continue
        merged[key] = dict(e)
    return list(merged.values())


def build_default_olostech_entries(
    retirada: Any, db: Any
) -> list[dict[str, Any]]:
    """Entradas com tipo padrao (Simples) para registro automatico.

    Itens sem olostech_id sao ignorados, como no dialogo.
    """
    entries: list[dict[str, Any]] = []
    for item in getattr(retirada, "itens", []) or []:
        db_id = str(getattr(item, "item_id", "") or "").strip()
        code = (db.get_olostech_id(db_id) or "") if (db and db_id) else ""
        if not code:
            continue
        entries.append({
            "material_code": code,
            "material_desc": getattr(item, "descricao", "") or "",
            "quantity": _to_int(getattr(item, "quantidade", 0), 0),
            "action_type": DEFAULT_ACTION_TYPE,
            "notificacao_nr": "",
            "dias": _to_int(getattr(item, "dias", 0), 0),
        })
    return merge_olostech_entries(entries)


class RegistrationWorker(QThread):
    """Worker thread para registro Olostech."""

    finished_with_result = Signal(bool, str)

    def __init__(
        self,
        olostech_cfg: dict[str, Any],
        patient_sus: str,
        professional_code: str,
        items: list[dict[str, Any]],
        ask_notificacao: (
            Callable[[str, int], tuple[int, str] | None] | None
        ) = None,
    ) -> None:
        super().__init__()
        self.olostech_cfg = olostech_cfg
        self.patient_sus = patient_sus
        self.professional_code = professional_code
        self.items = items
        self.ask_notificacao = ask_notificacao

    def run(self) -> None:
        try:
            from emissor.olostech.auth import OlostechAuth
            from emissor.olostech.dispensing import Dispensing

            from andaime.error_handler import ErrorContext, ErrorHandler, ErrorLevel

            # Converte OlostechConfig para dict se necessário
            cfg = self.olostech_cfg
            if hasattr(cfg, "to_dict"):
                cfg = cfg.to_dict()

            # Roteia os logs do olostech para o emissor.log da aplicação
            def _log_cb(msg: str) -> None:
                ErrorHandler.log(msg, level=ErrorLevel.INFO, context=ErrorContext.APP)

            auth = OlostechAuth(cfg, log_callback=_log_cb)
            if not auth.machine_auth():
                self.finished_with_result.emit(
                    False, "Falha na autenticacao de maquina"
                )
                return
            if not auth.user_login():
                self.finished_with_result.emit(False, "Falha no login")
                return
            # Failed dispensations dump form+response here for diagnosis.
            debug_path = Path(tempfile.gettempdir()) / (
                "olostech_debug_"
                + datetime.now().strftime("%Y%m%d_%H%M%S")
                + ".html"
            )
            disp = Dispensing(auth, log_callback=_log_cb, debug_file=str(debug_path))
            success, message = disp.dispense_retirada(
                patient_sus=self.patient_sus,
                professional_code=self.professional_code,
                items=self.items,
                ask_notificacao=self.ask_notificacao,
            )
            if not success and debug_path.exists():
                _log_cb(f"Debug da falha salvo em: {debug_path}")
            self.finished_with_result.emit(success, message)
        except Exception as e:
            self.finished_with_result.emit(False, f"Erro: {e}")


def show_olostech_dialog(
    parent: QWidget,
    retirada: Retirada,
    patient: Patient,
) -> list[dict[str, Any]] | None:
    """Coleta dados do registro manual; o runner executa em background."""
    dialog, layout = scaffold_dialog(
        parent, "Registrar Olostech", min_width=640
    )

    # Area rolável: info do paciente + itens
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QScrollArea.Shape.NoFrame)
    scroll.setMaximumHeight(560)

    content = QWidget()
    content_layout = QVBoxLayout(content)
    content_layout.setContentsMargins(0, 0, 0, 0)
    content_layout.setSpacing(12)

    # Info do paciente
    patient_name = getattr(patient, "nome", "?") or "?"
    info = QLabel(f"Paciente: {patient_name}")
    info.setStyleSheet("font-weight: bold;")
    content_layout.addWidget(info)

    # Itens
    form = QFormLayout()
    form.setSpacing(8)

    rows: list[_ItemRow] = []

    items = getattr(retirada, "itens", [])

    # Obtem DB via parent (MainWindow tem atributo db)
    db_obj = getattr(parent, "db", None)

    for idx, item in enumerate(items):
        descricao = getattr(item, "descricao", "") or ""
        quantidade = getattr(item, "quantidade", "") or ""
        db_id = str(getattr(item, "item_id", "") or "").strip()
        olostech_code = (
            (db_obj.get_olostech_id(db_id) or "") if (db_obj and db_id) else ""
        )

        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)

        label = QLabel(f"{descricao}  x{quantidade}")
        label.setMinimumWidth(200)
        row_layout.addWidget(label)

        combo = NoScrollComboBox()
        combo.setMaximumWidth(180)
        for action_id, action_label in ACTION_LABELS.items():
            combo.addItem(action_label, action_id)
        row_layout.addWidget(combo)

        notif_edit = QLineEdit()
        notif_edit.setPlaceholderText("Nr. Notificacao")
        notif_edit.setEnabled(False)
        notif_edit.setMaximumWidth(120)
        row_layout.addWidget(notif_edit)

        def _on_change(
            _index: int = 0,
            c: QComboBox = combo,
            e: QLineEdit = notif_edit,
        ) -> None:
            e.setEnabled(c.currentData() in NOTIFICATION_ACTIONS)

        combo.currentIndexChanged.connect(_on_change)

        if not olostech_code:
            label.setText(f"{descricao}  x{quantidade}  (SEM MAPEAMENTO)")
            label.setStyleSheet("color: gray;")
            combo.setEnabled(False)
            notif_edit.setEnabled(False)

        rows.append(_ItemRow(item, combo, notif_edit, olostech_code))
        form.addRow(row_widget)

    content_layout.addLayout(form)

    scroll.setWidget(content)
    layout.addWidget(scroll)

    # Botoes (tematizados, como os demais dialogos)
    btn_row, (cancel_btn, ok_btn) = make_dialog_button_row(
        [("Cancelar", "flat"), ("Registrar", "primary")]
    )
    layout.addLayout(btn_row)

    result: list[dict[str, Any]] | None = None

    def _collect_items() -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for row in rows:
            if not row.olostech_code:
                continue

            action_type = row.combo.currentData()
            entries.append({
                "material_code": row.olostech_code,
                "material_desc": getattr(row.item, "descricao", "") or "",
                "quantity": _to_int(getattr(row.item, "quantidade", 0), 0),
                "action_type": action_type,
                "notificacao_nr": (
                    row.notif_edit.text().strip()
                    if action_type in NOTIFICATION_ACTIONS
                    else ""
                ),
                "dias": _to_int(getattr(row.item, "dias", 0), 0),
            })
        return merge_olostech_entries(entries)

    def _on_accepted() -> None:
        nonlocal result

        # Coletar dados e fechar — o registro roda no chamador.
        collected = _collect_items()
        if not collected:
            QMessageBox.warning(
                dialog,
                "Sem mapeamento",
                "Nenhum item com mapeamento Olostech.",
            )
            return
        result = collected
        dialog.accept()

    ok_btn.clicked.connect(_on_accepted)
    cancel_btn.clicked.connect(dialog.reject)

    dialog.exec()
    return result


def patient_matricula(patient: Any) -> str:
    """Retorna a matrícula/SUS do paciente, truncando após '/'."""
    for attr in ("matricula", "sus", "id"):
        val = getattr(patient, attr, None)
        if val is not None:
            sus = str(val).strip()
            if "/" in sus:
                sus = sus.split("/")[0].strip()
            return sus
    return "?"


def patient_crm(patient: Any) -> str:
    """Retorna o CRM do paciente ou um valor de fallback."""
    crm = str(getattr(patient, "profissional_crm", "") or "").strip()
    if crm:
        return crm
    # Fallback aceito pela plataforma Olostech
    return "12345"


def _to_int(value: Any, default: int = 0) -> int:
    """Converte valores para int sem falhar."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
