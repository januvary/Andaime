#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Olostech Authentication & Login Automation.

Implementa a cadeia completa de autenticação Olostech:
  1. Autenticação de máquina (SHA-1 de endereços MAC)
  2. Rotação de domínio
  3. Fluxo de login (credenciais -> unidade -> ambiente -> perfil)

O formato do hash MAC (reverse-engineered do Java SaudeTech.exe) é:
    SHA-1( mac_address|os_name|os_arch|processor_count )
Codificação ISO-8859-1, saída em minúsculas.
"""

from __future__ import annotations

import hashlib
import os
import platform
import re
import socket
import subprocess
import sys
import time
import uuid
from datetime import datetime
from typing import Any

import requests
import urllib3

from emissor.olostech.exceptions import OlostechAuthError, OlostechConfigError

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# ---------------------------------------------------------------------------
# Helpers de autenticação de máquina
# ---------------------------------------------------------------------------

BLACKLISTED_MACS = {"000000000000", "020054554e01", "000100012f9b"}


def get_physical_mac_addresses(log_callback: Any | None = None) -> list[str]:
    """Coleta endereços MAC físicos (estilo Java MacAddress).

    Exclui MACs da blacklist e endereços localmente administrados (virtuais).
    Retorna lista de strings hex minúsculas sem separadores.

    Tenta até 3 vezes (com espera) — na inicialização do sistema a rede
    pode não estar pronta, causando WinError 50. Se ipconfig falhar,
    usa uuid.getnode() como fallback.
    """
    def log(msg: str) -> None:
        if log_callback:
            log_callback(msg)
        else:
            print(f"[MAC] {msg}")

    def _collect_from_ipconfig() -> list[str]:
        result = subprocess.run(
            ["ipconfig", "/all"],
            capture_output=True,
            text=True,
            timeout=10,
            stdin=None,
        )
        lines = result.stdout.split("\n")
        log(f"ipconfig /all returned {len(lines)} lines")

        found: list[str] = []
        for line in lines:
            # Aceita ambos formatos: com traços ou sem separadores
            mac_match = re.search(
                r"([0-9A-Fa-f]{2}[:-][0-9A-Fa-f]{2}[:-][0-9A-Fa-f]{2}-"
                r"[0-9A-Fa-f]{2}[:-][0-9A-Fa-f]{2}[:-][0-9A-Fa-f]{2})|"
                r"([0-9A-Fa-f]{12})",
                line,
            )
            if not mac_match:
                continue

            # Pega o grupo que teve match
            mac_hex = (mac_match.group(1) or mac_match.group(2) or "").replace("-", "").replace(":", "").lower()

            if mac_hex in BLACKLISTED_MACS:
                log(f"MAC blocked (blacklist): {mac_hex}")
                continue

            # Filtra MACs localmente administrados (adaptadores virtuais)
            first_octet = int(mac_hex[:2], 16)
            if first_octet & 0x02:
                log(f"MAC blocked (locally administered): {mac_hex}")
                continue

            if mac_hex not in found:
                found.append(mac_hex)
                log(f"MAC accepted: {mac_hex}")
        return found

    macs: list[str] = []

    # Tenta ipconfig até 3 vezes com espera (rede pode não estar pronta no boot)
    for attempt in range(1, 4):
        try:
            macs = _collect_from_ipconfig()
            if macs:
                break
            log(f"ipconfig tentativa {attempt} retornou nenhum MAC")
        except Exception as e:
            log(f"Exception collecting MACs (tentativa {attempt}): {e}")
        if attempt < 3:
            log("Aguardando 2s antes de nova tentativa...")
            time.sleep(2)

    # Fallback: uuid.getnode() usa a primeira interface não-virtual disponível
    if not macs:
        try:
            node = uuid.getnode()
            if node is not None and node != 0:
                mac_hex = f"{node:012x}"
                # Aplica o mesmo filtro de MACs virtual/locally administered
                if mac_hex in BLACKLISTED_MACS:
                    log(f"uuid.getnode() blocked (blacklist): {mac_hex}")
                else:
                    first_octet = int(mac_hex[:2], 16)
                    if first_octet & 0x02:
                        log(f"uuid.getnode() blocked (locally administered): {mac_hex}")
                    else:
                        macs.append(mac_hex)
                        log(f"MAC via uuid.getnode(): {mac_hex}")
        except Exception as e:
            log(f"Exception in uuid.getnode fallback: {e}")

    log(f"Final MAC list: {macs}")
    log(f"Generating hashes for {len(macs)} MAC(s)")
    return macs


def java_style_os_name() -> str:
    """Retorna o os.name como o Java reporta.

    O Java (JDK 8u321+/11.0.13+/17+) reporta "Windows 11" em builds
    >= 22000, enquanto platform.release() do Python sempre retorna "10".
    O hash registrado pelo launcher Java usa o nome do Java — precisamos
    reproduzi-lo exatamente.
    """
    if platform.system() != "Windows":
        return f"{platform.system()} {platform.release()}"
    try:
        build = sys.getwindowsversion().build
    except Exception:
        build = 0
    return "Windows 11" if build >= 22000 else "Windows 10"


def generate_mac_hash(mac_hex: str) -> str:
    """Gera SHA-1 exatamente como a aplicação Java faz.

    Formato: SHA-1( mac_hex|os.name|os.arch|processor_count )
    Codificação ISO-8859-1.
    """
    os_name = java_style_os_name()
    os_arch = platform.machine().lower()
    cpu_count = os.cpu_count()

    input_string = f"{mac_hex}|{os_name}|{os_arch}|{cpu_count}"
    return hashlib.sha1(input_string.encode("iso-8859-1")).hexdigest()


def build_machine_auth_params(log_callback: Any | None = None) -> tuple[str, str]:
    """Monta parâmetros macaddress e dados para conferir.asp.

    Retorna (macaddress_param, dados_param):
      macaddress = hash1,hash2,...
      dados = mac1|os|arch,mac2|os|arch,...
    """
    macs = get_physical_mac_addresses(log_callback)
    if not macs:
        raise OlostechAuthError("Nenhum endereço MAC físico encontrado")

    hashes = [generate_mac_hash(mac) for mac in macs]

    os_info = f"{java_style_os_name()}|{platform.machine()}".lower()
    dados_parts = [f"{mac}|{os_info}" for mac in macs]

    return ",".join(hashes), ",".join(dados_parts)


# ---------------------------------------------------------------------------
# Autenticação
# ---------------------------------------------------------------------------

class OlostechAuth:
    """Gerencia autenticação e login na plataforma Olostech."""

    def __init__(
        self,
        config: dict[str, Any],
        log_callback: Any | None = None,
    ) -> None:
        """Inicializa com configuração Olostech.

        Args:
            config: dict com as chaves obrigatórias:
                username, password, lst_acesso, unit, environment, role,
                aceite_chave.
            log_callback: função opcional para receber mensagens de log.
        """
        self._validate_config(config)
        self.config = config
        self._log_cb = log_callback
        self.session = requests.Session()
        self.session.verify = False
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/91.0.4472.124 Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;"
                "q=0.9,*/*;q=0.8"
            ),
        })
        self.active_domain: str | None = None
        self.lst_acesso: str = config["lst_acesso"]

    @staticmethod
    def _validate_config(config: dict[str, Any]) -> None:
        """Garante que a configuração possui todas as chaves obrigatórias."""
        required = {
            "username",
            "password",
            "lst_acesso",
            "unit",
            "environment",
            "role",
            "aceite_chave",
        }
        missing = required - set(config.keys())
        if missing:
            raise OlostechConfigError(
                f"Configuração Olostech incompleta. Faltam: {sorted(missing)}"
            )

    def _log(self, msg: str, level: str = "INFO") -> None:
        if self._log_cb:
            self._log_cb(f"[{level}] {msg}")
        else:
            print(f"[{level}] {msg}")

    def log(self, msg: str, level: str = "INFO") -> None:
        """Público para uso por módulos auxiliares (PatientAttendance etc.)."""
        self._log(msg, level)

    # ------------------------------------------------------------------
    # FASE 1: Autenticação de máquina
    # ------------------------------------------------------------------

    def machine_auth(self) -> bool:
        """Executa o protocolo de 3 passos de autenticação de máquina."""
        self._log("=== FASE 1: Autenticação de Máquina ===")

        # Passo 1: Verificação de disponibilidade
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        resp = self.session.get(
            f"http://www.olostech.com.br/saudeweb/acesso/"
            f"bloqueio.asp?dt={timestamp}",
            timeout=60,
        )
        parts = resp.text.split("|")
        self._log(f"  bloqueio.asp: {parts[0]}")
        if not parts[0].startswith("1"):
            self._log(f"Sistema bloqueado: {resp.text}", "ERROR")
            return False

        # Passo 2: Autenticação de máquina
        macaddress_hash, dados = build_machine_auth_params(self._log_cb)
        resp = self.session.get(
            "https://www.olostech.com.br/v4/conferir.asp",
            params={"macaddress": macaddress_hash, "dados": dados},
            timeout=60,
        )
        parts = resp.text.split("|")
        if len(parts) < 3 or parts[0] != "1":
            self._log(f"Máquina não reconhecida: {resp.text}", "ERROR")
            return False

        id1, id2 = parts[1], parts[2]
        self._log(f"  conferir.asp: máquina OK (id2={id2})")

        # Passo 3: verifica.asp redireciona para domínio w[x]
        resp = self.session.get(
            f"https://www.olostech.com.br/verifica.asp?id={id1}&id2={id2}",
            timeout=60,
        )
        redirect_match = re.search(
            r"enviarForm\([^,]+,\s*['\"]([^'\"]+)['\"]", resp.text
        )
        if not redirect_match:
            self._log("Nenhum redirecionamento encontrado em verifica.asp", "ERROR")
            return False

        redirect_url = redirect_match.group(1)
        domain_match = re.search(r"https?://([^/]+)", redirect_url)
        self.active_domain = domain_match.group(1) if domain_match else None
        self._log(f"  verifica.asp: redirecionado para {self.active_domain}")

        self.session.get(redirect_url, timeout=60)

        lst_match = re.search(
            r'name="lstAcesso"[^>]*value="([^"]+)"', resp.text
        )
        if lst_match:
            self.lst_acesso = lst_match.group(1)
            self._log(f"  lstAcesso: {self.lst_acesso}")
        else:
            self._log("  lstAcesso não encontrado, usando configuração", "WARN")

        self._log("Autenticação de máquina concluída.")
        return True

    # ------------------------------------------------------------------
    # FASE 2: Login de usuário
    # ------------------------------------------------------------------

    def _check_errors(self, text: str, step_name: str) -> list[str] | None:
        """Extrai mensagens de erro visíveis do HTML."""
        errors = re.findall(r"color:#FF0000[^>]*>([^<]+)<", text)
        if errors:
            self._log(f"  {step_name}: ERROS = {errors}", "ERROR")
            return errors
        return None

    def _extract_fields(self, text: str) -> list[str]:
        """Extrai nomes de campos input do HTML."""
        return re.findall(r'<input[^>]+name="([^"]+)"', text)

    def user_login(self) -> bool:
        """Executa o fluxo de login na plataforma Olostech."""
        if not self.active_domain:
            self._log("Nenhum domínio ativo - execute machine_auth() primeiro", "ERROR")
            return False

        base = f"https://{self.active_domain}"
        self._log(f"=== FASE 2: Login em {self.active_domain} ===")

        cfg = self.config

        # Passo 1: Inicializa sessão
        self._log("  [1] POST logon.asp?origem=0")
        resp = self.session.post(
            f"{base}/logon.asp?origem=0",
            data={"lstAcesso": self.lst_acesso},
            timeout=60,
        )
        if self._check_errors(resp.text, "origem=0"):
            return False

        inputs = self._extract_fields(resp.text)
        self._log(f"  Campos encontrados: {inputs}")

        user_field = pass_field = None
        for name in inputs:
            if "nome" in name.lower() and "logon" in name.lower():
                user_field = name
            elif "senha" in name.lower():
                pass_field = name

        if not user_field or not pass_field:
            self._log("Campos de credencial não encontrados, usando padrões HAR", "WARN")
            user_field = user_field or "txtNomeLogon_919135703"
            pass_field = pass_field or "txtSenhaLogon_919135703"

        self._log(f"  Usando: {user_field}, {pass_field}")

        # Passo 2: Envia credenciais
        self._log("  [2] POST logon.asp?origem=1")
        resp = self.session.post(
            f"{base}/logon.asp?origem=1",
            data={
                user_field: cfg["username"],
                pass_field: cfg["password"],
                "lstAcesso": self.lst_acesso,
            },
            timeout=60,
        )
        if self._check_errors(resp.text, "origem=1"):
            return False

        olosid_match = re.search(r"olosid=([A-F0-9]{20,})", resp.text)
        olosid = olosid_match.group(1) if olosid_match else None

        # Passo 3: Redirecionamento para saudeweb
        if olosid:
            self._log(f"  [3] POST redirect_logon.asp (olosid={olosid[:16]}...)")
            resp = self.session.post(
                f"{base}/saudeweb/acesso/redirect_logon.asp?olosid={olosid}",
                data={
                    "lstAcesso": self.lst_acesso,
                    "txtIdentificacao": olosid,
                },
                timeout=60,
            )
            if self._check_errors(resp.text, "redirect"):
                return False
        else:
            self._log("  [3] olosid não encontrado, pulando redirecionamento", "WARN")

        # Passo 4: Inicialização saudeweb
        self._log("  [4] POST saudeweb logon.asp?origem=0")
        resp = self.session.post(
            f"{base}/saudeweb/acesso/logon.asp?origem=0",
            timeout=60,
        )
        if self._check_errors(resp.text, "saudeweb origem=0"):
            return False

        # Passo 5: Seleção de unidade
        self._log("  [5] POST saudeweb logon.asp?origem=1 (unidade)")
        resp = self.session.post(
            f"{base}/saudeweb/acesso/logon.asp?origem=1",
            data={
                "txtChaveControleAceite": cfg["aceite_chave"],
                "lstUnidades": cfg["unit"],
            },
            timeout=60,
        )
        if self._check_errors(resp.text, "unit"):
            return False

        # Passo 6: Seleção de ambiente
        self._log("  [6] POST saudeweb logon.asp?origem=2 (ambiente)")
        resp = self.session.post(
            f"{base}/saudeweb/acesso/logon.asp?origem=2",
            data={
                "lstUnidades": cfg["unit"],
                "lstAmbientes": cfg["environment"],
            },
            timeout=60,
        )
        if self._check_errors(resp.text, "environment"):
            return False

        # Passo 7: Perfil profissional
        self._log("  [7] POST saudeweb logon.asp?origem=3 (perfil)")
        resp = self.session.post(
            f"{base}/saudeweb/acesso/logon.asp?origem=3",
            data={
                "lstUnidades": cfg["unit"],
                "lstAmbientes": cfg["environment"],
                "lstAtividadeProfissional": cfg["role"],
            },
            timeout=60,
        )
        if self._check_errors(resp.text, "role"):
            return False

        # Passo 8: Configuração de sessão
        self._log("  [8] POST session.asp")
        self.session.post(
            f"{base}/saudeweb/acesso/session.asp",
            data={"lstAtividadeProfissional": cfg["role"]},
            timeout=60,
        )

        # Passos 9-11: Chamadas de gravação de cookies
        self._log("  [9] POST grava_logon.asp")
        self.session.post(
            f"{base}/saudeweb/acesso/cookie/grava_logon.asp",
            timeout=60,
        )
        self._log("  [10] POST grava_logon.asp?origem=2")
        self.session.post(
            f"{base}/saudeweb/acesso/cookie/grava_logon.asp?origem=2",
            timeout=60,
        )
        self._log("  [11] POST grava_logon.asp?origem=1")
        self.session.post(
            f"{base}/saudeweb/acesso/cookie/grava_logon.asp?origem=1",
            timeout=60,
        )

        # Passo 12: Carrega aplicação principal
        self._log("  [12] POST saudeweb/default.asp")
        self.session.post(
            f"{base}/saudeweb/default.asp",
            timeout=60,
        )

        self._log("Login concluído.")
        return True

    def verify_application_access(self) -> bool:
        """Verifica se conseguimos acessar a aplicação principal após login."""
        self._log("=== FASE 3: Verificar Acesso à Aplicação ===")
        if not self.active_domain:
            return False

        base = f"https://{self.active_domain}"
        resp = self.session.get(f"{base}/saudeweb/", timeout=60)
        self._log(f"  saudeweb/ status: {resp.status_code}")
        self._log(f"  Cookies: {len(self.session.cookies)}")

        errors = self._check_errors(resp.text, "app access")
        if errors:
            self._log("Acesso à aplicação falhou.", "ERROR")
            return False

        self._log("Acesso à aplicação verificado.")
        return True
