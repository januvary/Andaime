#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validation Module — validação de dados de paciente para PDF/DB."""

from typing import Tuple, List, Optional, Dict, Any


class PatientDataValidator:
    """Valida dados de paciente para geração de PDF e operações de banco."""

    @staticmethod
    def validate_for_pdf_generation(
        selected_patient: Optional[Dict[str, Any]],
        processo_n: str,
        item_rows: List[Any],
        periodicidade: str,
        data_retirada_str: str | None = None,
        tipo: str | None = None,
    ) -> Tuple[bool, str]:
        """Valida campos obrigatórios para gerar PDF. Retorna (is_valid, msg).

        ``tipo`` é o tipo selecionado na UI (fonte da verdade). Pacientes do
        tipo "insulina" não exigem número de processo.
        """
        errors = []

        if not selected_patient or not selected_patient.get("nome"):
            errors.append("- Paciente não selecionado")

        # O tipo vem da seleção atual da UI, não do registro salvo do paciente.
        is_insulina = tipo == "insulina"

        if not is_insulina and (not processo_n or not processo_n.strip()):
            errors.append("- Processo Nº não preenchido")

        if not item_rows:
            errors.append("- Nenhum item adicionado")
        else:
            has_items = any(row.get("descricao") for row in item_rows if row)

            if not has_items:
                errors.append("- Nenhum item adicionado")
            else:
                for idx, item_row in enumerate(item_rows, start=1):
                    item_data = item_row

                    descricao = item_data.get("descricao", "").strip()
                    item_id = item_data.get("item_id", "").strip()
                    unidade = item_data.get("unidade", "").strip()
                    quantidade = item_data.get("quantidade", "").strip()
                    dias = item_data.get("dias", "").strip()

                    if not descricao:
                        errors.append(f"- Item {idx}: campo 'descrição' não preenchido")
                    if not item_id:
                        errors.append(f"- Item {idx}: campo 'item ID' não preenchido")
                    if not unidade:
                        errors.append(f"- Item {idx}: campo 'unidade' não preenchido")
                    if not quantidade:
                        errors.append(f"- Item {idx}: campo 'quantidade' não preenchido")
                    if not dias:
                        errors.append(f"- Item {idx}: campo 'dias' não preenchido")

        if (
            not periodicidade
            or not periodicidade.strip()
            or not periodicidade.strip().isdigit()
        ):
            errors.append("- Periodicidade não preenchida")

        if data_retirada_str is not None:
            if not data_retirada_str.strip():
                errors.append("- Data da Retirada não preenchida")
            else:
                try:
                    from andaime.dates import parse_date

                    parsed_date = parse_date(data_retirada_str)
                    if not parsed_date:
                        errors.append(
                            "- Data da Retirada inválida (use formato DD/MM/AAAA)"
                        )
                except ImportError:
                    # holidays indisponível — validação básica (p/ Olostech, etc.)
                    from datetime import datetime

                    try:
                        datetime.strptime(data_retirada_str, "%d/%m/%Y")
                    except ValueError:
                        errors.append(
                            "- Data da Retirada inválida (use formato DD/MM/AAAA)"
                        )

        if errors:
            error_msg = "Campos obrigatórios faltando:\n\n" + "\n".join(errors)
            return False, error_msg

        return True, ""
