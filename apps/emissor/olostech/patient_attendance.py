#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gerenciamento de atendimento de paciente no dispensário Olostech.

Fluxo:
  1. Carrega atendimento.asp (página do dispensário)
  2. Busca paciente por SUS via usuario.ajax.asp
  3. Verifica/inicia atendimento via atendimento.ajax.asp
"""

from __future__ import annotations

import re
from typing import Any

from emissor.olostech.auth import OlostechAuth


class PatientAttendance:
    """Gerencia busca de paciente e abertura de atendimento no dispensário."""

    def __init__(self, auth: OlostechAuth) -> None:
        self.auth = auth
        self.base = f"https://{auth.active_domain}"
        self.page_values: dict[str, str] = {}

    def load_atendimento_page(self) -> bool:
        """Carrega a página de atendimento e extrai campos hidden."""
        self.auth.log("Carregando página de atendimento...")
        resp = self.auth.session.get(
            f"{self.base}/saudeweb/amfb/fb/atendimento.asp", timeout=60
        )

        if resp.status_code != 200:
            self.auth.log(
                f"Falha ao carregar página de atendimento: {resp.status_code}",
                "ERROR",
            )
            return False

        fields = [
            "txtEstoqueDispensario",
            "txtAtendimentoData",
            "txtAtendimentoNr",
            "txtParametroValidacao_txtUsuarioAtendimentoMatricula",
            "txtExistePendencia",
        ]
        for field in fields:
            match = re.search(
                rf'name="{re.escape(field)}"[^>]*value="([^"]*)"', resp.text
            )
            if match:
                self.page_values[field] = match.group(1)

        self.auth.log(
            f"  Estoque: {self.page_values.get('txtEstoqueDispensario', '?')}"
        )
        self.auth.log(
            f"  Data: {self.page_values.get('txtAtendimentoData', '?')}"
        )

        # A página chama obterSenhaAtual() via JS para obter senha atual
        estoque = self.page_values.get("txtEstoqueDispensario", "505")
        self.auth.log("  Obtendo número da senha atual...")
        resp = self.auth.session.post(
            f"{self.base}/saudeweb/amfb/fb/atendimento.ajax.asp",
            data={"funcao": "obterSenhaAtual", "dados": estoque},
            timeout=60,
        )

        senha_match = re.search(
            r"<senha><!\[CDATA\[([^\]]*)\]\]></senha>", resp.text
        )
        if senha_match:
            self.page_values["txtAtendimentoNr"] = senha_match.group(1)
            self.auth.log(f"  Senha: {self.page_values['txtAtendimentoNr']}")

        return True

    def lookup_patient(self, sus_number: str) -> dict[str, str] | None:
        """Busca paciente pelo número SUS."""
        self.auth.log(f"Buscando paciente SUS={sus_number}...")

        param_val = self.page_values.get(
            "txtParametroValidacao_txtUsuarioAtendimentoMatricula",
            "2|#true|#true|#false|#true",
        )
        param_parts = param_val.split("|#")

        dados = "|#".join([
            sus_number,
            param_parts[0],
            param_parts[4] if len(param_parts) > 4 else "true",
        ])

        resp = self.auth.session.post(
            f"{self.base}/saudeweb/classe/usuario.ajax.asp",
            data={"funcao": "obterUsuarioSUS", "dados": dados},
            timeout=60,
        )

        fields: dict[str, str] = {}
        for m in re.finditer(
            r"<(\w+)><!\[CDATA\[([^\]]*)\]\]></\1>", resp.text
        ):
            fields[m.group(1)] = m.group(2)

        if not fields:
            self.auth.log("  Paciente não encontrado", "ERROR")
            return None

        if int(fields.get("ExclusaoRef", 0)) > 0:
            self.auth.log(
                f"  Paciente marcado como DUPLICADO - use matrícula "
                f"{fields['ExclusaoRef']} ao invés disso", "WARN"
            )
            return None

        if fields.get("situacao_obito") == "1":
            self.auth.log("  Paciente possui registro de ÓBITO", "ERROR")
            return None

        if fields.get("situacao") == "0":
            self.auth.log("  Paciente INATIVO no sistema", "WARN")

        self.auth.log(f"  Encontrado: {fields.get('usuarionome', '?')}")
        self.auth.log(
            f"  Idade: {fields.get('idade', '?')}, "
            f"Bairro: {fields.get('bairrodesc', '?')}"
        )

        return fields

    def check_duplicate_attendance(self, sus_number: str) -> dict[str, str]:
        """Verifica se paciente já possui atendimento hoje."""
        self.auth.log("Verificando atendimento existente...")

        estoque = self.page_values.get("txtEstoqueDispensario", "505")
        data = self.page_values.get("txtAtendimentoData", "")
        senha = self.page_values.get("txtAtendimentoNr", "1")

        dados = "|#".join([estoque, data, sus_number, senha])

        resp = self.auth.session.post(
            f"{self.base}/saudeweb/amfb/fb/atendimento.ajax.asp",
            data={
                "funcao": "verificarControleRepeticaoAtendimento",
                "dados": dados,
            },
            timeout=60,
        )

        result: dict[str, str] = {}
        for m in re.finditer(
            r"<(\w+)><!\[CDATA\[([^\]]*)\]\]></\1>", resp.text
        ):
            result[m.group(1)] = m.group(2)

        concluido = result.get("concluido", "")
        mensagem = result.get("mensagem", "")
        self.auth.log(f"  concluido={concluido}, mensagem={mensagem}")

        return result

    def start_attendance(self, attendance_id: str) -> Any:
        """Abre um atendimento existente por ID (origem=1)."""
        self.auth.log(f"Abrindo atendimento ID={attendance_id}...")
        resp = self.auth.session.post(
            f"{self.base}/saudeweb/amfb/fb/"
            f"atendimento.asp?origem=1&Atendimento={attendance_id}",
            timeout=60,
        )

        title = re.search(r"<title>([^<]+)</title>", resp.text)
        if title:
            self.auth.log(f"  Título: {title.group(1).strip()}")

        return resp

    def open_attendance(self, sus_number: str) -> bool:
        """Fluxo completo: busca paciente, verifica duplicados, abre atendimento."""
        if not self.load_atendimento_page():
            return False

        patient = self.lookup_patient(sus_number)
        if not patient:
            return False

        check = self.check_duplicate_attendance(sus_number)

        if check.get("mensagem", "").isdigit():
            attendance_id = check["mensagem"]
            self.auth.log(f"Novo atendimento criado: ID={attendance_id}")
            self.start_attendance(attendance_id)
            return True

        if check.get("concluido") == "True":
            self.auth.log("Paciente já possui atendimento hoje", "WARN")

            estoque = self.page_values.get("txtEstoqueDispensario", "505")
            data = self.page_values.get("txtAtendimentoData", "")
            dados = "|#".join([estoque, data, sus_number])

            resp = self.auth.session.post(
                f"{self.base}/saudeweb/amfb/fb/atendimento.ajax.asp",
                data={
                    "funcao": "obterListaAtendimentoPaciente",
                    "dados": dados,
                },
                timeout=60,
            )

            attendance_ids = re.findall(r"Atendimento=(\d+)", resp.text)
            if attendance_ids:
                self.auth.log(f"  IDs existentes: {attendance_ids}")
                self.auth.log(f"  Abrindo mais recente: {attendance_ids[-1]}")
                self.start_attendance(attendance_ids[-1])
                return True
            else:
                self.auth.log("  Não foi possível extrair IDs de atendimento", "WARN")
                return False

        self.auth.log(f"  Não foi possível iniciar atendimento: {check}", "ERROR")
        return False
