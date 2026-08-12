#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Complete Olostech dispensing automation.

Flow (reverse-engineered from HAR):
  1. Auth + login
  2. Open attendance for patient
  3. Look up professional
  4. Open dispensacao_direta page
  5. Look up material + add item
  6. Conclude attendance
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from emissor.olostech.auth import OlostechAuth
from emissor.olostech.patient_attendance import PatientAttendance


class Dispensing:
    """Handles the complete dispensing flow."""

    def __init__(self, auth: OlostechAuth, log_callback=None, debug_file: str | None = None):
        self.auth = auth
        self._log_cb = log_callback
        self.debug_file = debug_file
        self.base = f"https://{auth.active_domain}"
        self.attendance_id = None
        self.chavepu = None
        self.dispensacao_id = None
        self.estoque = "505"
        self.unit_code = "2867"
        self._item_chaves = []
        self._patient_sus = None
        self._action_type = None

    def _log(self, msg, level="INFO"):
        if self._log_cb:
            self._log_cb(f"[{level}] {msg}")
        else:
            print(f"[{level}] {msg}")

    def add_stock(self, material_recnum, quantity_needed, current_saldo=0,
                  loterecnum="", lote_desc="", lote_validade=""):
        """Add stock via acerto (acrescimo) to cover a dispensation.

        Adds exactly: quantity_needed - current_saldo.
        For lot-controlled materials, pass loterecnum/lote_desc/lote_validade.
        """
        shortfall = quantity_needed - current_saldo
        if shortfall <= 0:
            return True

        today = datetime.now().strftime("%d/%m/%Y")
        self._log(f"  Adding stock: +{shortfall} (need {quantity_needed}, have {current_saldo})")

        # Step 1: Open the acerto page (sets session context)
        self.auth.session.get(
            f"{self.base}/saudeweb/AMFB/MOV/acerto_acrescimo.asp?origem=0",
            timeout=60,
        )

        # Step 2: Get estoque info
        self.auth.session.post(
            f"{self.base}/saudeweb/AMFB/MOV/acerto.ajax.asp",
            data={"funcao": "obterEstoqueUnidade", "dados": self.unit_code},
            timeout=60,
        )

        # Step 3: Get current acerto list
        self.auth.session.post(
            f"{self.base}/saudeweb/AMFB/MOV/acerto.ajax.asp",
            data={"funcao": "obterListaAcerto", "dados": f"true|#{today}"},
            timeout=60,
        )

        # Step 4: Get material info for acerto
        self.auth.session.post(
            f"{self.base}/saudeweb/AMFB/MOV/acerto.ajax.asp",
            data={"funcao": "ObterMaterialAcrescimo",
                  "dados": f"{self.estoque}|#{material_recnum}"},
            timeout=60,
        )

        # Step 5: GravarAcertoEstoque - add the stock
        # Field order from JS: true, motivo, date, estoque, material,
        #   quantity, justificativa, NrLaudo, lstLote, formulario,
        #   null, numeracaoInicial, numeracaoFinal
        dados_parts = [
            "true",           # [0]
            "1",              # [1] motivo: acrescimo
            today,            # [2] date
            self.estoque,     # [3] estoque
            material_recnum,  # [4] material code
            str(shortfall),   # [5] quantity
            "acerto",         # [6] justificativa
            "",               # [7] NrLaudo
            loterecnum,       # [8] lstLote (lot recnum)
            "",               # [9] formulario
            "",               # [10] null
            "",               # [11] numeracaoInicial
            "",               # [12] numeracaoFinal
        ]
        dados = ")#|#(".join(dados_parts)

        resp = self.auth.session.post(
            f"{self.base}/saudeweb/AMFB/MOV/acerto.ajax.asp",
            data={"funcao": "GravarAcertoEstoque", "dados": dados},
            timeout=60,
        )

        result = {}
        for m in re.finditer(r"<(\w+)><!\[CDATA\[([^\]]*)\]\]></\1>", resp.text):
            result[m.group(1)] = m.group(2)

        if result.get("concluido") == "True":
            self._log(f"  Stock adjusted: +{shortfall}")
            return True
        else:
            self._log(f"  Stock adjustment failed: {result}", "ERROR")
            return False

    def open_attendance(self, patient_sus):
        """Create/open attendance and set up session state for dispensing."""
        self._log(f"=== Attendance for patient {patient_sus} ===")

        pa = PatientAttendance(self.auth)
        pa.load_atendimento_page()
        patient = pa.lookup_patient(patient_sus)
        if not patient:
            return False

        self.estoque = pa.page_values.get("txtEstoqueDispensario", "505")
        data = pa.page_values.get("txtAtendimentoData", "")
        senha = pa.page_values.get("txtAtendimentoNr", "1")

        # Duplicate check - creates new attendance ID if none exists
        dados = "|#".join([self.estoque, data, patient_sus, senha])
        resp = self.auth.session.post(
            f"{self.base}/saudeweb/amfb/fb/atendimento.ajax.asp",
            data={"funcao": "verificarControleRepeticaoAtendimento",
                  "dados": dados},
            timeout=60,
        )

        result = {}
        for m in re.finditer(r"<(\w+)><!\[CDATA\[([^\]]*)\]\]></\1>", resp.text):
            result[m.group(1)] = m.group(2)

        mensagem = result.get("mensagem", "")

        if mensagem.isdigit():
            self.attendance_id = mensagem
            self._log(f"  New attendance: {self.attendance_id}")
        elif result.get("concluido") == "True" and mensagem == "Verificar":
            # Patient has existing attendance(s) - fetch them
            dados2 = "|#".join([self.estoque, data, patient_sus])
            resp2 = self.auth.session.post(
                f"{self.base}/saudeweb/amfb/fb/atendimento.ajax.asp",
                data={"funcao": "obterListaAtendimentoPaciente",
                      "dados": dados2},
                timeout=60,
            )
            ids = re.findall(r'iniciarAtendimento\((\d+)\)', resp2.text)
            if ids:
                self.attendance_id = ids[-1]
                self._log(f"  Existing attendance: {self.attendance_id}")
            else:
                self._log("  Could not extract attendance ID", "ERROR")
                return False
        else:
            self._log(f"  Unexpected response: {result}", "ERROR")
            return False

        # Open attendance (origem=1)
        self.auth.session.post(
            f"{self.base}/saudeweb/amfb/fb/"
            f"atendimento.asp?origem=1&Atendimento={self.attendance_id}",
            data={
                "txtEstoqueDispensario": self.estoque,
                "txtAtendimentoData": data,
                "txtAtendimentoNr": senha,
                "txtUsuarioAtendimentoMatricula": patient_sus,
                "txtExistePendencia": "false",
                "rdoPacientePresente": "1",
                "rdTipoPesquisa": "simples",
                "txtAtendimentoConcluidoData": data,
            },
            timeout=60,
        )

        # Return to attendance menu (origem=0) - critical for session state
        self.auth.session.post(
            f"{self.base}/saudeweb/amfb/fb/atendimento.asp?origem=0",
            data={
                "txtAtendimentoChave": self.attendance_id,
                "txtRetornoPopUpAssinar": "0",
                "txtPortadorMatricula": patient_sus,
                "txtPacienteMatricula": patient_sus,
                "txtAtendimentoData": data,
                "txtCarregarReceitaAutomaticamente": "1",
                "txtIniciarAcaoSelecaoReceita": "1",
                "txtUsarUltimoPrescritor": "1",
                "txtPermitirRenovarReceita": "True",
                "txtPrazoQtdeDiasVencida": "30",
                "txtPrazoQtdeDiasVencer": "0",
                "txtMatricula": patient_sus,
                "rdoProfissional": "4",
            },
            timeout=60,
        )
        self._log("  Session state ready")
        return True

    def lookup_professional(self, professional_code):
        """Look up professional, store chavepu."""
        self._log(f"=== Professional {professional_code} ===")
        resp = self.auth.session.post(
            f"{self.base}/saudeweb/amfb/fb/atendimento.ajax.asp",
            data={"funcao": "ObterDadosProfissional",
                  "dados": f"4|#{professional_code}"},
            timeout=60,
        )

        fields = {}
        for m in re.finditer(r"<(\w+)><!\[CDATA\[([^\]]*)\]\]></\1>", resp.text):
            fields[m.group(1)] = m.group(2)

        if not fields or "chavepu" not in fields:
            self._log(f"  Not found", "ERROR")
            return False

        self.chavepu = fields["chavepu"]
        self.professional_code = professional_code
        self._log(f"  {fields.get('profissionalnome', '?')} (chavepu={self.chavepu})")
        return True

    # Action types: controlado/notificacao flags
    CONTROLLED_ACTIONS = {4, 6, 7, 9}  # Especial, Notif B, Notif A, Talidomida
    NOTIFICATION_ACTIONS = {6, 7, 9}   # Notif B, Notif A, Talidomida (need notif nr)

    def open_dispensacao_direta(self, patient_sus, action_type=2,
                                 notificacao_nr="", receita_data=""):
        """Open the dispensacao_direta page.
        
        For controlled actions (4,6,7,9), notificacao_nr and receita_data
        are required.
        """
        # Reset dispensacao_id for new session
        self.dispensacao_id = None

        self._log(f"=== Opening dispensacao_direta (action={action_type}) ===")

        # verificarTipoAcao (required before opening)
        self.auth.session.post(
            f"{self.base}/saudeweb/amfb/fb/atendimento.ajax.asp",
            data={"funcao": "verificarTipoAcao", "dados": str(action_type)},
            timeout=60,
        )

        form_data = {
            "txtAtendimentoChave": self.attendance_id,
            "txtRetornoPopUpAssinar": "0",
            "txtPortadorMatricula": patient_sus,
            "txtPacienteMatricula": patient_sus,
            "txtAtendimentoData": "",
            "txtCarregarReceitaAutomaticamente": "1",
            "txtIniciarAcaoSelecaoReceita": "1",
            "txtUsarUltimoPrescritor": "1",
            "txtPermitirRenovarReceita": "True",
            "txtPrazoQtdeDiasVencida": "30",
            "txtPrazoQtdeDiasVencer": "0",
            "rdoTipoAcao": str(action_type),
            "rdoProfissional": "4",
            "txtPesquisa_4": getattr(self, "professional_code", ""),
            "lstProfissionalUnidade": self.chavepu,
            "txtMatricula": patient_sus,
        }

        # Add controlled substance fields if needed
        if action_type in self.CONTROLLED_ACTIONS:
            form_data["txtModeloReceitaControlada"] = "true"
            form_data["txtNotificacaoNr"] = notificacao_nr
            form_data["txtReceitaControladaData"] = receita_data or \
                datetime.now().strftime("%d/%m/%Y")
            # Store for add_item to use
            self.notificacao_nr = notificacao_nr
            self.receita_data = form_data["txtReceitaControladaData"]
        else:
            form_data["txtModeloReceitaControlada"] = "false"
            self.notificacao_nr = ""
            self.receita_data = ""

        resp = self.auth.session.post(
            f"{self.base}/saudeweb/amfb/fb/dispensacao_direta.asp?origem=0",
            data=form_data,
            timeout=60,
        )

        title = re.search(r"<title>([^<]+)</title>", resp.text)
        if title:
            self._log(f"  {title.group(1).strip()}")

        errors = re.findall(r"color:#FF0000[^>]*>([^<]+)<", resp.text)
        if errors:
            self._log(f"  Errors: {errors}", "ERROR")
            return False

        return resp.status_code == 200

    def _lookup_material(self, material_code):
        """Try material lookup, handling code format differences.
        Olostech CSV codes are 5-digit (e.g. 35286) while the server's
        ObterMaterialDispensacao expects the internal recnum (e.g. 3528),
        which is the CSV code divided by 10. Always try the direct code
        first, then the recnum form."""
        codes = [str(material_code)]
        if str(material_code).isdigit():
            codes.append(str(int(material_code) // 10))

        for code in codes:
            resp = self.auth.session.post(
                f"{self.base}/saudeweb/amfb/fb/dispensacao.ajax.asp",
                data={"funcao": "ObterMaterialDispensacao", "dados": code},
                timeout=60,
            )
            mat = {}
            for m in re.finditer(r"<(\w+)><!\[CDATA\[([^\]]*)\]\]></\1>", resp.text):
                mat[m.group(1)] = m.group(2)
            if mat:
                if code != str(material_code):
                    self._log(
                        f"  NOTE: material {material_code} matched via "
                        f"recnum fallback {code}", "WARN"
                    )
                return mat
        return None

    def add_item(self, patient_sus, material_code, material_desc,
                 quantity, action_type=2, dias=0):
        """Look up material and add it to the dispensation."""
        self._log(f"=== Adding: {material_desc} x{quantity} ===")
        self._patient_sus = patient_sus
        self._action_type = action_type

        mat = self._lookup_material(material_code)
        if not mat:
            self._log(f"  Material {material_code} not found", "ERROR")
            return False

        material_recnum = mat.get("materialrecnum", str(int(material_code) // 10))
        saldo = mat.get("saldo_atual", mat.get("saldotemp", "0"))
        controla_lote = mat.get("controlalote", "0")
        alerta_qtde = mat.get("alertaqtdeentrega", "0")
        medicamento_recnum = mat.get("medicamentorecnum", "")
        self._log(f"  Found: {mat.get('materialdesc', '?')} "
            f"(recnum={material_recnum}, saldo={saldo})")

        is_medication = bool(medicamento_recnum)

        # Supporting AJAX calls
        if is_medication:
            # Medication flow: lookup medication dispensation data
            resp_med = self.auth.session.post(
                f"{self.base}/saudeweb/amfb/fb/dispensacao.ajax.asp",
                data={"funcao": "ObterMedicamentoDispensacao",
                      "dados": f"{medicamento_recnum}|#|#{action_type}|#|#{patient_sus}|#|#0"},
                timeout=60,
            )
            # Parse medication data
            med_data = {}
            for m in re.finditer(r"<(\w+)><!\[CDATA\[([^\]]*)\]\]></\1>", resp_med.text):
                med_data[m.group(1)] = m.group(2)

            # Last delivery of medication (not material)
            self.auth.session.post(
                f"{self.base}/saudeweb/amfb/fb/dispensacao.ajax.asp",
                data={"funcao": "obterUltimaEntregaMedicamento",
                      "dados": f"{patient_sus}|#{medicamento_recnum}"},
                timeout=60,
            )
        else:
            # Non-medication flow (fraldas, supplies)
            self.auth.session.post(
                f"{self.base}/saudeweb/amfb/fb/dispensacao.ajax.asp",
                data={"funcao": "obterUltimaEntregaMaterial",
                      "dados": f"{patient_sus}|#{material_recnum}"},
                timeout=60,
            )

        self.auth.session.post(
            f"{self.base}/saudeweb/amfb/fb/dispensacao.ajax.asp",
            data={"funcao": "ObterMaterialAssociado",
                  "dados": f"{material_recnum}|#"},
            timeout=60,
        )
        
        # Get lot info (critical for lot-controlled items like insulin)
        loterecnum = ""
        lote_desc = ""
        lote_validade = ""
        if controla_lote == "1":
            resp_lots = self.auth.session.post(
                f"{self.base}/saudeweb/amfb/fb/dispensacao.ajax.asp",
                data={"funcao": "obterLotesMedicamento",
                      "dados": f"{material_recnum}#"},
                timeout=60,
            )
            # Extract all lot fields
            lot_match = re.search(r"<loterecnum><!\[CDATA\[([^\]]*)\]\]>", resp_lots.text)
            lote_desc_match = re.search(r"<lote><!\[CDATA\[([^\]]*)\]\]>", resp_lots.text)
            validade_match = re.search(r"<data_validade><!\[CDATA\[([^\]]*)\]\]>", resp_lots.text)
            if lot_match:
                loterecnum = lot_match.group(1)
                lote_desc = lote_desc_match.group(1) if lote_desc_match else ""
                lote_validade = validade_match.group(1) if validade_match else ""
                self._log(f"  Lot: {loterecnum} ({lote_desc}, validade: {lote_validade})")
        else:
            self.auth.session.post(
                f"{self.base}/saudeweb/amfb/fb/dispensacao.ajax.asp",
                data={"funcao": "obterLotesMedicamento",
                      "dados": f"{material_recnum}#"},
                timeout=60,
            )

        # Check stock before attempting dispensation
        current_saldo = int(saldo) if str(saldo).isdigit() else 0
        if current_saldo < quantity:
            self._log(f"  Insufficient stock (have {current_saldo}, need {quantity})")
            if not self.add_stock(material_recnum, quantity, current_saldo,
                                  loterecnum, lote_desc, lote_validade):
                self._log("  Cannot proceed without stock", "ERROR")
                return False
            saldo = str(quantity)

        # Build form data
        is_controlled = action_type in self.CONTROLLED_ACTIONS
        
        # Use existing dispensacao_id if we're adding to an open dispensation
        disp_chave = self.dispensacao_id if self.dispensacao_id else "0"
        
        form_data = {
            "txtEstoqueDispensario": self.estoque,
            "txtAtendimentoData": "",
            "txtAtendimentoChave": self.attendance_id,
            "txtDispensacaoChave": disp_chave,
            "txtMatricula": patient_sus,
            "lstProfissionalUnidade": self.chavepu,
            "rdoTipoAcao": str(action_type),
            "txtReceitaModelo": "0",
            "txtReceitaModeloControlado": str(is_controlled),
            "txtEdicaoConferencia": "False",
            "txtQtdeDiaAlertaSuficiencia": "5",
            "txtPermitirAlterarQtdePrescrita": "False",
            "txtPermitirEntregarMaiorPrescrita": "True",
            "txtJustificarEntregaMaiorPrescrita": "False",
            "txtAlertarEntregaMaiorPrescrita": "True",
            "txtRetornoPopUpAssinar": "0",
            "txtMaterialControlaLote": controla_lote,
            "txtAlertaQtdeEntrega": alerta_qtde,
            "txtQtdePrescricaoUnidMed": "1" if is_medication else "0",
            "obrigarDispensacaoCodigoBarras": "false",
            "txtMaterialCod": str(material_code),
            "txtMaterialDesc": mat.get("materialdesc", material_desc),
            "txtQtdeAplicacoes": "1",
            "lstFrequencia": "1|#1",
            "txtSaldoAtual": saldo,
            "txtQtdeEntrega": str(quantity),
        }

        # Lot-controlled fields (insulin, etc.)
        if controla_lote == "1" and loterecnum:
            form_data["lstLote"] = loterecnum
            form_data["txtQuantidadeDoLote"] = str(quantity)

        # Medication-specific fields
        if is_medication:
            duracao_raw = med_data.get("duracao_tratamento_max", "30")
            try:
                duracao_max = int(duracao_raw) if str(duracao_raw).isdigit() else 30
            except (ValueError, TypeError):
                duracao_max = 30
            # The JS sets txtQtdePrescricaoUnidMed from the MATERIAL lookup
            # (obterDadosMaterial.Value("Qtde_Unidade_Medida")), not the
            # medication lookup.
            qtde_unid = mat.get("qtde_unidade_medida") or \
                        med_data.get("qtde_unidade_medida") or "1"
            form_data["txtDuracaoTratamento"] = str(duracao_max)

            try:
                unid = int(qtde_unid) if str(qtde_unid).isdigit() else 1
            except (ValueError, TypeError):
                unid = 1
            total_units = quantity * unid
            real_dias = dias if dias and dias > 0 else quantity

            # The server rejects a posology whose duration (txtQtdeDias)
            # exceeds the medication's max treatment duration
            # (txtDuracaoTratamento). Pick an integer (dose, dias) pair with
            #   dias <= duracao_max  and  dias * dose == quantity * unid
            # so the server's prescrita (dose*apps*days/unid) equals the
            # quantity exactly and no '.' decimal is ever sent.
            dose_val = dose_dias = None
            if duracao_max >= real_dias and total_units % real_dias == 0:
                dose_val = total_units // real_dias
                dose_dias = real_dias
            else:
                for d in range(max(1, duracao_max), 0, -1):
                    if total_units % d == 0:
                        dv = total_units // d
                        if dv > 0:
                            dose_val, dose_dias = dv, d
                            break
                if dose_val is None:
                    dose_val, dose_dias = total_units, 1

            prescrita = (dose_dias * dose_val) // unid

            self._log(f"  Posology: dose={dose_val}, days={dose_dias}, "
                      f"unid={unid}, max_days={duracao_max}, "
                      f"prescrita={prescrita}")

            # Integer dose -> plain digits (never a '.' which the server
            # treats as a thousands separator, nor a ',' which is fine).
            form_data["txtQtdeDose"] = str(dose_val)
            form_data["txtQtdeAplicacoes"] = "1"
            form_data["txtQtdeDias"] = str(dose_dias)
            form_data["txtQtdePrescrita"] = str(prescrita)
            form_data["txtQtdePrescricaoUnidMed"] = qtde_unid

        # Controlled fields (txtReceitaModeloControlado already set)
        if is_controlled:
            form_data["txtReceitaControladaData"] = getattr(
                self, "receita_data", "")

        # Notification number only for Notificação types
        if action_type in self.NOTIFICATION_ACTIONS:
            form_data["txtNotificacaoNr"] = getattr(self, "notificacao_nr", "")

        # Add the item (origem=1)
        resp = self.auth.session.post(
            f"{self.base}/saudeweb/amfb/fb/dispensacao_direta.asp?origem=1",
            data=form_data,
            timeout=60,
        )

        title = re.search(r"<title>([^<]+)</title>", resp.text)
        self._log(f"  Result: {title.group(1).strip() if title else 'no title'}")

        # Extract visible error messages from the response
        def _dump_debug(fd, html):
            if not self.debug_file:
                return
            try:
                with open(self.debug_file, "w", encoding="utf-8") as f:
                    f.write("<!-- FORM SENT:\n")
                    for k, v in fd.items():
                        f.write(f"{k}={v}\n")
                    f.write("-->\n")
                    f.write(html)
            except Exception as e:
                self._log(f"Falha ao salvar debug HTML: {e}", "WARN")

        def _extract_errors(html):
            """Pull meaningful error text from HTML responses."""
            lines = []
            # The server often reports errors via JS alert() calls
            for m in re.finditer(r"alert\(\s*(['\"])(.*?)\1\s*\)", html,
                                 re.DOTALL):
                msg = m.group(2).replace("\\n", " | ").replace("\n", " ").strip()
                if msg and msg not in lines:
                    lines.append(msg)
            body = re.sub(r"<style[^>]*>.*?</style>", "", html,
                          flags=re.DOTALL)
            body = re.sub(r"<script[^>]*>.*?</script>", "", body,
                          flags=re.DOTALL)
            body_text = re.sub(r"<[^>]+>", "\n", body)
            for line in body_text.split("\n"):
                line = line.strip()
                if not line or len(line) < 3:
                    continue
                lower = line.lower()
                if any(kw in lower for kw in [
                    "aten", "erro", "invalid", "inválid", "finalizado",
                    "obrigat", "saldo", "sufici", "estoque", "lote",
                    "material", "prescrit", "permiss", "negado",
                    "justific", "quantidade",
                ]):
                    if line not in lines:
                        lines.append(line)
            return lines

        text_lower = resp.text.lower()
        is_failure = (resp.status_code == 500 or
                      "color:#ff0000" in resp.text.lower() or
                      "não foi finalizado" in text_lower or
                      "material informado" in text_lower)
        if is_failure:
            _dump_debug(form_data, resp.text)
            errors = _extract_errors(resp.text)
            if not errors:
                errors = ["(no readable error message)"]
            for line in errors[:8]:
                self._log(f"  Server: {line}", "ERROR")
            return False

        # Extract dispensation ID and item chave
        disp_match = re.search(r"Dispensacao=(\d+)", resp.text)
        if disp_match:
            self.dispensacao_id = disp_match.group(1)
            self._log(f"  Dispensacao ID: {self.dispensacao_id}")

        # The origem=1 response does not render the item rows: the browser
        # auto-reloads via
        #   enviarForm(null,'dispensacao_direta.asp?origem=0&Dispensacao=<id>')
        # which shows the items. Re-open the page and capture the item
        # chaves (btnCancelar<chave>) so we can roll them back on failure.
        if self.dispensacao_id:
            self._refresh_item_chaves()

        if disp_match:
            return True

        # If we already have a dispensacao_id and response looks clean,
        # the item was likely added to the existing dispensation
        if self.dispensacao_id and resp.status_code == 200:
            self._log(f"  Added to dispensation {self.dispensacao_id}")
            return True

        self._log("  No dispensation ID found - item may not have been saved",
                  "WARN")
        return False

    def _refresh_item_chaves(self):
        """Re-open the dispensation page to list its items and capture the
        chaves needed to cancel them on rollback.

        The item rows render on the page as:
            <input ... id="btnCancelar<chave>" ... onClick="...">
        """
        if not self.dispensacao_id:
            return

        data = {
            "txtEstoqueDispensario": self.estoque,
            "txtAtendimentoData": "",
            "txtAtendimentoChave": self.attendance_id,
            "nIdRecepcao": "",
            "txtDispensacaoChave": self.dispensacao_id,
            "txtMatricula": self._patient_sus or "",
            "lstProfissionalUnidade": self.chavepu,
            "rdoTipoAcao": str(self._action_type if self._action_type else 2),
            "txtReceitaModelo": "0",
            "txtReceitaModeloControlado": "False",
            "txtNotificacaoNr": "",
            "txtReceitaControladaData": "",
            "txtCIDChave": "",
            "txtEdicaoConferencia": "false",
            "txtQtdeDiaAlertaSuficiencia": "5",
            "txtPermitirAlterarQtdePrescrita": "False",
            "txtPermitirEntregarMaiorPrescrita": "True",
            "txtJustificarEntregaMaiorPrescrita": "False",
            "txtAlertarEntregaMaiorPrescrita": "True",
            "txtRetornoPopUpAssinar": "0",
        }

        resp = self.auth.session.post(
            f"{self.base}/saudeweb/amfb/fb/dispensacao_direta.asp"
            f"?origem=0&Dispensacao={self.dispensacao_id}",
            data=data,
            timeout=60,
        )

        chaves = re.findall(r"btnCancelar(\d+)", resp.text)
        if not chaves:
            chaves = re.findall(
                r"ObterDispensacoesRecentesCancelar\(\s*-?\d+\s*,\s*\d+\s*,"
                r"\s*(\d+)", resp.text
            )
        if chaves:
            self._item_chaves = sorted(set(chaves))
            self._log(f"  Item chaves: {self._item_chaves}")
        else:
            self._log("  No item chaves found on re-opened dispensation",
                      "WARN")

    def rollback_dispensation(self, justificativa="Cancelamento por falha na dispensação"):
        """Cancel dispensed items, then cancel the attendance.

        The server blocks cancelarAtendimento while dispensation item
        records exist. Manual flow is: cancel each item via
        dispensacao_item_cancelar_popup.asp?origem=1, then cancel the
        attendance.
        """
        self._log(f"=== Rolling back dispensation (attendance {self.attendance_id}) ===")

        items = list(getattr(self, "_item_chaves", []))
        if not items and self.dispensacao_id:
            self._log("  No item chaves captured yet - refreshing from "
                      "dispensation page", "WARN")
            self._refresh_item_chaves()
            items = list(getattr(self, "_item_chaves", []))

        if not items:
            self._log("  No item chaves found - cannot roll back items",
                      "WARN")

        ok = True
        for chave in items:
            resp = self.auth.session.post(
                f"{self.base}/saudeweb/amfb/fb/"
                f"dispensacao_item_cancelar_popup.asp?origem=1",
                data={
                    "txtDispensacaoItem": chave,
                    "txtJustificativa": justificativa,
                },
                timeout=60,
            )
            if "sucesso" in resp.text.lower():
                self._log(f"  Item {chave} cancelled")
            else:
                self._log(f"  Item {chave} cancel result: "
                          f"{resp.text[:200]}", "WARN")
                ok = False

        # Now the attendance can be cancelled
        return self.cancel_attendance(justificativa) and ok

    def cancel_attendance(self, justificativa="Atendimento aberto por engano"):
        """Cancel the currently open attendance.

        Mirrors the JS in atendimento_cancelar_popup.asp:
            dados = txtAtendimentoChave + "|#" + justificativa + "|#0|#0"
        (no recepcao in the automated flow, so the last two params are 0).

        Returns True on success.
        """
        self._log(f"=== Cancelling attendance {self.attendance_id} ===")
        if not self.attendance_id:
            self._log("  No attendance to cancel", "WARN")
            return False

        dados = f"{self.attendance_id}|#{justificativa}|#0|#0"
        resp = self.auth.session.post(
            f"{self.base}/saudeweb/amfb/fb/atendimento.ajax.asp",
            data={"funcao": "cancelarAtendimento", "dados": dados},
            timeout=60,
        )

        result = {}
        for m in re.finditer(r"<(\w+)><!\[CDATA\[([^\]]*)\]\]></\1>", resp.text):
            result[m.group(1)] = m.group(2)

        if result.get("concluido") == "True":
            self._log(f"  Attendance {self.attendance_id} cancelled")
            return True
        else:
            self._log(f"  Cancel failed: {result.get('mensagem', 'unknown')}",
                      "ERROR")
            return False

    def conclude(self):
        """Conclude the attendance."""
        self._log("=== Concluding ===")

        # Post-dispense checks
        self.auth.session.post(
            f"{self.base}/saudeweb/amfb/fb/atendimento.ajax.asp",
            data={"funcao": "verificarPendenciasAssinaturaDigital",
                  "dados": self.attendance_id},
            timeout=60,
        )
        self.auth.session.post(
            f"{self.base}/saudeweb/amfb/fb/atendimento.ajax.asp",
            data={"funcao": "verificarDispensacaoMedicamentoEmCasa",
                  "dados": self.attendance_id},
            timeout=60,
        )

        # Conclude
        resp = self.auth.session.post(
            f"{self.base}/saudeweb/amfb/fb/atendimento.ajax.asp",
            data={"funcao": "concluirAtendimento",
                  "dados": self.attendance_id},
            timeout=60,
        )

        result = {}
        for m in re.finditer(r"<(\w+)><!\[CDATA\[([^\]]*)\]\]></\1>", resp.text):
            result[m.group(1)] = m.group(2)

        if result.get("concluido") == "True":
            self._log(f"  SUCCESS: {result.get('mensagem', '')}")
            dispensed = self.list_dispensed_items()
            if dispensed:
                self._log("  Dispensed items:")
                for it in dispensed:
                    self._log(f"    {it['code']}  {it['desc']}  x{it['qty']}")
            else:
                self._log("  (no items found on receipt)")
            return True
        else:
            self._log(f"  FAILED: {result.get('mensagem', 'unknown')}", "ERROR")
            return False

    def list_dispensed_items(self):
        """Fetch the dispensation receipt and return the items dispensed.

        Calls rel_fb_dispensacao_recibo.asp?Origem=0&Dispensacao=<id> which
        renders a receipt table. Each item is a <tbody class="linha"> block
        with a code/description/qty row (and an optional lot sub-row).

        Returns a list of dicts: [{"code":..., "desc":..., "qty":...}, ...]
        """
        if not self.dispensacao_id:
            return []

        resp = self.auth.session.get(
            f"{self.base}/saudeweb/amfb/rel/rel_fb_dispensacao_recibo.asp"
            f"?tCabecalho=&args=&Origem=0&Dispensacao={self.dispensacao_id}",
            timeout=60,
        )

        items = []
        for block in re.findall(
            r'<tbody class="linha">(.*?)</tbody>', resp.text, re.DOTALL
        ):
            # First <tr> holds code + description + quantity
            first = re.search(
                r'<td[^>]*align="right"[^>]*>\s*(\d+)</td>\s*'
                r'<td[^>]*colspan="\d+"[^>]*>(.*?)</td>\s*'
                r'.*?<td[^>]*>\s*<b>\s*(\d+)\s*</b>\s*</td>',
                block, re.DOTALL,
            )
            if first:
                code = first.group(1)
                desc = re.sub(r"<[^>]+>", "", first.group(2)).strip()
                qty = first.group(3)
                items.append({"code": code, "desc": desc, "qty": qty})
        return items

    def dispense(self, patient_sus, professional_code, material_code,
                 material_desc, quantity, action_type=2,
                 notificacao_nr="", receita_data=""):
        """One-call single-item dispensing flow (wraps dispense_retirada)."""
        item = {
            "material_code": material_code,
            "material_desc": material_desc,
            "quantity": quantity,
            "action_type": action_type,
            "notificacao_nr": notificacao_nr,
            "dias": 0,
        }
        return self.dispense_retirada(patient_sus, professional_code, [item])

    def dispense_retirada(self, patient_sus, professional_code, items):
        """Multi-item, multi-type dispensing for a full retirada.

        Args:
            patient_sus: Patient SUS number
            professional_code: CRM or Olostech professional code
            items: List of dicts with keys:
                - material_code: Olostech CSV code
                - material_desc: Description
                - quantity: int
                - action_type: 2/4/6/7/9
                - notificacao_nr: str (for controlled, can be "")

        Flow:
            1. Open attendance (once)
            2. Look up professional (once)
            3. Group items by action_type
            4. For each group: open_dispensacao_direta → add each item
            5. Conclude attendance (once)
        """
        if not items:
            self._log("No items to dispense", "ERROR")
            return False

        # Step 1: Open attendance
        if not self.open_attendance(patient_sus):
            return False

        # Step 2: Look up professional
        if not self.lookup_professional(professional_code):
            self._log("Trying fallback professional code '12345'", "WARN")
            if not self.lookup_professional("12345"):
                return False

        # Step 3: Filter out zero-quantity items, group by action_type
        valid_items = [it for it in items if it.get("quantity", 0) > 0]
        skipped_zero = len(items) - len(valid_items)
        if skipped_zero:
            self._log(f"Skipping {skipped_zero} item(s) with quantity 0")
        if not valid_items:
            self._log("No items with quantity > 0", "ERROR")
            return False

        groups = {}
        for item in valid_items:
            at = item.get("action_type", 2)
            if at not in groups:
                groups[at] = []
            groups[at].append(item)

        self._log(f"\n=== Dispensing {len(valid_items)} item(s) in {len(groups)} group(s) ===")

        # Track successes
        succeeded = []
        failed = []

        # Step 4: Process each group
        for action_type, group_items in groups.items():
            notif = group_items[0].get("notificacao_nr", "")

            self._log(f"\n--- Group: action_type={action_type} ({len(group_items)} item(s)) ---")

            if not self.open_dispensacao_direta(patient_sus, action_type, notif):
                self._log(f"Failed to open dispensacao for action {action_type}", "ERROR")
                for item in group_items:
                    failed.append(item["material_desc"])
                continue

            for item in group_items:
                if not self.add_item(
                    patient_sus,
                    item["material_code"],
                    item["material_desc"],
                    item["quantity"],
                    action_type,
                    item.get("dias", 0),
                ):
                    self._log(f"  FAILED: {item['material_desc']}", "ERROR")
                    failed.append(item["material_desc"])
                else:
                    self._log(f"  OK: {item['material_desc']} x{item['quantity']}")
                    succeeded.append(item["material_desc"])

        # Report results
        self._log(f"\n=== Results: {len(succeeded)} succeeded, {len(failed)} failed ===")
        if failed:
            self._log(f"Failed items: {', '.join(failed)}", "WARN")

        # If any item failed, don't conclude - roll back so no
        # orphaned-open attendance (or partial dispensation) is left behind.
        if failed:
            self._log("One or more items failed - rolling back attendance", "ERROR")
            if succeeded or self._item_chaves:
                self.rollback_dispensation()
            else:
                self.cancel_attendance()
            return False

        return self.conclude()
