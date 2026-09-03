"""HTML document builder for Sistema de Negativas"""

from typing import List

from negativas.models import ItemSelecionado, Medicamento, NegativaData
from negativas.constants import BRASAO_HEIGHT
from negativas.utils import data_por_extenso, svg_base64

try:
    from negativas.ui_qt.theme import colors
except ImportError:
    # Fallback for non-Qt contexts
    def colors():
        return {"text": "#000000"}


class DocumentBuilder:
    """Builds HTML documents from form data."""

    def __init__(self, db):
        self.db = db
        self._medicamentos_cache: dict[str, Medicamento] = {}
        self._medicamentos_cache_key: tuple[str, ...] | None = None

    def build_html(self, data: NegativaData, include_brasao: bool = True) -> str:
        """Gera HTML completo a partir dos dados do formulário."""
        div_texto = self._get_divisao_texto(data)
        data_hoje = data.data_hoje or data_por_extenso()
        nome_daf = data.nome_daf if data.nome_daf else "____________________"
        nome_dgmi = data.nome_dgmi if data.nome_dgmi else "____________________"

        parts = [
            self._build_html_header(data.destinatario, div_texto, include_brasao),
            self._build_itens_section(data.itens),
            "<br>",
            self._build_footer(
                data_hoje, nome_daf, nome_dgmi, data.usos_daf, data.usos_dgmi
            ),
        ]

        return "".join(parts)

    def _get_divisao_texto(self, data: NegativaData) -> str:
        """Determina o texto da divisão baseado nas seleções."""
        if data.usos_daf and data.usos_dgmi:
            return "Divisão de Assistência Farmacêutica e Divisão de Gestão de Materiais e Insumos"
        elif data.usos_daf:
            return "Divisão de Assistência Farmacêutica"
        elif data.usos_dgmi:
            return "Divisão de Gestão de Materiais e Insumos"
        else:
            return "Divisão de Assistência Farmacêutica e Divisão de Gestão de Materiais e Insumos"

    def _build_html_header(self, destinatario: str, div_texto: str, include_brasao: bool = True) -> str:
        """Constrói o cabeçalho HTML."""
        c = colors()
        text_color = c.get("text", "#000000")
        border_color = c.get("panel_border", "#000000")

        brasao_img = (
            f'<img class="brasao" height="{BRASAO_HEIGHT}" src="data:image/svg+xml;base64,{svg_base64()}" alt="Brasão da Prefeitura">'
            if include_brasao else ""
        )
        brasao_css = f'    .brasao {{ display: block; height: {BRASAO_HEIGHT}px; }}' if include_brasao else ""

        return f"""
<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <title>Negativa - {destinatario}</title>
  <style>
    body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 40px; line-height: 1.6; color: {text_color}; }}
    h1 {{ text-align: center; text-decoration: underline; font-size: 17px; margin-bottom: 2px; color: {text_color}; }}
    h2 {{ text-align: center; font-size: 14px; margin: 2px 0; color: {text_color}; }}
    h3 {{ text-align: center; font-size: 14px; margin: 0; color: {text_color}; }}
    p {{ color: {text_color}; }}
    b {{ color: {text_color}; }}
    .content {{ margin: 30px 0; }}
    .assinaturas {{ display: flex; justify-content: center; align-items: flex-start; margin-top: 50px; gap: 60px; }}
    .assinatura {{ text-align: center; flex: 1; }}
    .assinatura strong {{ font-size: 11pt; color: {text_color}; }}
    .assinatura span {{ font-size: 10pt; font-weight: bold; color: {text_color}; }}
    .header {{ display: flex; align-items: center; justify-content: center; gap: 50px; margin-bottom: 10px; }}
    .header-title {{ text-align: center; text-decoration: underline; font-size: 17px; margin: 0; color: {text_color}; }}
    .divider {{ border-top: 1px solid {border_color}; margin: 20px 0; }}
    {brasao_css}
    @media print {{ body {{ margin: 0; }} }}
  </style>
</head>
<body>
  <div class="header">
    {brasao_img}
    <div>
      <h1 class="header-title" style="font-size: 17px;">MUNICÍPIO DA ESTÂNCIA BALNEÁRIA DE PRAIA GRANDE</h1>
      <h2 style="font-size: 14px;">Estado de São Paulo</h2>
      <h3 style="font-size: 14px;">SESAP - Secretaria de Saúde Pública</h3>
    </div>
  </div>
  <div class="divider"></div>

  <div class="content">
    <p><b>À {destinatario},</b></p>
    <p>Ao que cabe à {div_texto}, informo o seguinte acerca dos medicamentos e insumos listados:</p>
"""

    def _build_itens_section(self, itens: List[ItemSelecionado]) -> str:
        """Constrói a seção de itens HTML."""
        if not itens:
            return "<p><i>Nenhum item adicionado ainda.</i></p>"

        ceaf_names = tuple(item.nome for item in itens if item.categoria == "CEAF")
        if ceaf_names != self._medicamentos_cache_key:
            self._medicamentos_cache = {}
            if ceaf_names:
                for med in self.db.get_medicamentos_por_nomes(list(ceaf_names)):
                    self._medicamentos_cache[med.nome] = med
            self._medicamentos_cache_key = ceaf_names

        parts: list[str] = []
        for item in itens:
            parts.append(self._build_item_html(item, self._medicamentos_cache))

        return "".join(parts)

    def _build_item_html(self, item: ItemSelecionado, medicamentos_cache: dict) -> str:
        """Constrói HTML para um item individual."""
        if item.categoria in ["CEAF", "USAFA", "CAPS II"]:
            return self._build_medicamento_html(item, medicamentos_cache)
        else:
            return self._build_nao_padronizado_html(item)

    def _build_medicamento_html(
        self, item: ItemSelecionado, medicamentos_cache: dict
    ) -> str:
        """Constrói HTML para medicamentos padronizados."""
        modelo_obj = self.db.get_modelo_por_categoria(item.categoria)
        modelo_texto = modelo_obj.texto if modelo_obj else ""

        parts = [f"<p><b>{item.nome}</b>: {modelo_texto}"]

        if item.categoria == "CEAF":
            med = medicamentos_cache.get(item.nome)
            if med and med.cids:
                prefix = "os CIDs de:" if len(med.cids) > 1 else "o CID de:"
                parts.append(f" contemplando {prefix} {', '.join(med.cids)}.")

        parts.append("</p>")

        if item.em_falta:
            modelo_falta = self.db.get_modelo_por_tipo("falta")
            if modelo_falta:
                parts.append(f"<p>{modelo_falta.texto}</p>")

        return "".join(parts)

    def _build_nao_padronizado_html(self, item: ItemSelecionado) -> str:
        """Constrói HTML para itens não padronizados."""
        tipo_modelo = (
            "nao_padronizado" if item.is_medicamento else "insumo_nao_padronizado"
        )
        modelo_obj = self.db.get_modelo_por_tipo(tipo_modelo)
        if modelo_obj:
            return f"<p><b>{item.nome}</b>: {modelo_obj.texto}</p>"
        return ""

    def _build_footer(
        self,
        data_hoje: str,
        nome_daf: str,
        nome_dgmi: str,
        usos_daf: bool,
        usos_dgmi: bool,
    ) -> str:
        """Constrói o rodapé HTML com assinaturas."""
        parts = [
            f'    <p style="text-align: right">Praia Grande, {data_hoje}.</p>',
            '    <p style="text-align: right">Atenciosamente,</p>',
            '    <div class="assinaturas">',
        ]

        if usos_daf:
            parts.append(f"""
      <div class="assinatura">
        <br><br>
        <strong>{nome_daf}</strong><br>
        <strong>DIVISÃO DE ASSISTÊNCIA FARMACÊUTICA</strong><br>
        <span>SESAP 10.2.02</span>
      </div>""")

        if usos_dgmi:
            parts.append(f"""
      <div class="assinatura">
        <br><br>
        <strong>{nome_dgmi}</strong><br>
        <strong>DIVISÃO DE GESTÃO DE MATERIAIS E INSUMOS</strong><br>
        <span>SESAP 10.6.1.3</span>
      </div>""")

        parts.append("    </div>")
        parts.append("  </div></body></html>")
        return "".join(parts)
