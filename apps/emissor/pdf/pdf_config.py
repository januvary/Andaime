#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Configurações e contexto de dados para geração de PDF."""

from dataclasses import dataclass
from typing import Dict, List, Any
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors


@dataclass
class PDFConfig:
    """Constantes centralizadas de layout, cores e fontes do PDF."""

    # ========================================================================
    # LAYOUT DA PÁGINA
    # ========================================================================

    pagesize = A4
    margin: float = 0.7 * cm

    # Dimensões calculadas (preenchidas em __post_init__)
    width: float = 0
    height: float = 0
    total_width: float = 0  # width - 2*margin

    # ========================================================================
    # LARGURAS DE COLUNAS (proporções do total_width)
    # ========================================================================

    # Header (logo + texto)
    COL_LOGO_WIDTH: float = 0.15
    COL_TEXT_WIDTH: float = 0.81

    # Patient info table
    COL_PATIENT_LABEL: float = 0.12
    COL_PATIENT_NAME: float = 0.48
    COL_PATIENT_EMPTY: float = 0.10
    COL_PATIENT_DATE: float = 0.30

    # Items table
    COL_ITEM_NUM: float = 0.06
    COL_ITEM_DESC: float = 0.49
    COL_ITEM_CODE: float = 0.18
    COL_ITEM_UNIT: float = 0.09
    COL_ITEM_QTY: float = 0.09
    COL_ITEM_DAYS: float = 0.09

    # Prescription dates and professional info
    COL_PRESC_WIDE: float = 0.55
    COL_PRESC_NARROW: float = 0.45

    # Hours section
    COL_HOURS_MORNING: float = 0.25
    COL_HOURS_AFTERNOON: float = 0.25
    COL_HOURS_PHONE: float = 0.50

    # ========================================================================
    # CORES
    # ========================================================================

    COLOR_BORDER = colors.black
    COLOR_HEADER_BG = colors.HexColor("#e8e8e8")

    # ========================================================================
    # TAMANHOS DE FONTE
    # ========================================================================

    FONT_SIZE_SMALL: int = 9
    FONT_SIZE_NORMAL: int = 11
    FONT_SIZE_MEDIUM: int = 12
    FONT_SIZE_LARGE: int = 13
    FONT_SIZE_EXTRA_LARGE: int = 13

    # ========================================================================
    # ESPAÇAMENTO (PADDING)
    # ========================================================================

    PADDING_SMALL: int = 2
    PADDING_MEDIUM: int = 3
    PADDING_LARGE: int = 4
    PADDING_XLARGE: int = 6
    PADDING_XXLARGE: int = 10
    PADDING_LOGO: int = 26  # LEFTPADDING específico para logo

    # ========================================================================
    # CONFIGURAÇÕES DE SVG
    # ========================================================================

    LOGO_TARGET_SIZE: float = 1.8 * cm
    LOGO_OFFSET_Y: float = -0.0 * cm

    # ========================================================================
    # OUTROS
    # ========================================================================

    SPACER_SMALL: int = 6

    def __post_init__(self) -> None:
        """Calcula dimensões derivadas após inicialização."""
        self.width, self.height = self.pagesize
        self.total_width = self.width - 2 * self.margin


@dataclass
class PDFDataContext:
    """Dados validados e prontos para uso pelos builders de tabelas PDF."""

    paciente: Dict[str, Any]
    itens: List[Dict[str, Any]]
    datas: Dict[str, Any]
    avisos: Dict[str, Any]
    observacoes: str
    atendido_por: str

    @classmethod
    def from_raw_data(cls, data: Dict[str, Any]) -> "PDFDataContext":
        """Cria contexto validado a partir de dados brutos da GUI."""
        # Validar campos obrigatórios
        required_fields = ["patient_name", "processos", "itens", "datas"]
        missing = [field for field in required_fields if field not in data]

        if missing:
            raise ValueError(f"Campos obrigatórios faltando: {missing}")

        # Helper function para mapear tipo de receita
        def get_texto_validade(tipo_receita: str) -> str:
            """Mapeia tipo de receita para texto de validade."""
            avisos_map = {
                "tipo_a": "a cada 6 meses",
                "tipo_b": "a cada 3 meses",
                "tipo_c": "mensalmente - MEDICAMENTO SUJEITO A CONTROLE ESPECIAL",
            }
            return avisos_map.get(tipo_receita, "periodicamente")

        # Construir dados do paciente
        processos = data.get("processos", [])

        paciente_data = {
            "nome": data["patient_name"],
            "processo_n": processos[0] if processos else "",
            "processos": processos,
            "tipo": data.get("tipo"),
            "profissional_nome": data.get("profissional_nome", ""),
            "profissional_crm": data.get("profissional_crm", ""),
            "matricula": data.get("matricula", ""),
        }

        # Dados dos itens (validar estrutura)
        itens_data = data.get("itens", [])
        for item in itens_data:
            if not all(
                key in item
                for key in ("descricao", "item_id", "unidade", "quantidade", "dias")
            ):
                raise ValueError(f"Item inválido: {item}")

        # Datas
        datas_data = data.get("datas", {})

        # Avisos dinâmicos baseados no tipo de receita
        tipo_receita = data.get("tipo_receita", "")
        texto_validade = get_texto_validade(tipo_receita)

        # Verificar se deve mostrar aviso DRS-IV
        tipo = data.get("tipo")
        mostra_drs_iv = tipo in ("revezado", "municipal_e_revezado")

        # Bloqueio de balanço do almoxarifado
        mostra_balanco = bool(data.get("bloquear_balanco", False))

        # Observações
        observacoes = data.get("observacoes", "")

        # Atendido por
        atendido_por = data.get("atendido_por", "")

        # Construir avisos
        avisos_data = {
            "texto_validade": texto_validade,
            "mostra_drs_iv": mostra_drs_iv,
            "mostra_balanco": mostra_balanco,
        }

        return cls(
            paciente=paciente_data,
            itens=itens_data,
            datas=datas_data,
            avisos=avisos_data,
            observacoes=observacoes,
            atendido_por=atendido_por,
        )
