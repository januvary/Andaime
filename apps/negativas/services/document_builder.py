"""HTML document builder for Sistema de Negativas"""

from typing import List

from negativas.models import ItemSelecionado, NegativaData
from negativas.constants import BRASAO_HEIGHT
from negativas.utils import data_por_extenso, svg_base64


class DocumentBuilder:
    """Builds HTML documents from form data."""
    
    def __init__(self, db):
        self.db = db
    
    def build_html(self, data: NegativaData) -> str:
        """Gera HTML completo a partir dos dados do formulário."""
        div_texto = self._get_divisao_texto(data)
        data_hoje = data_por_extenso()
        nome_daf = data.nome_daf if data.nome_daf else "____________________"
        nome_dgmi = data.nome_dgmi if data.nome_dgmi else "____________________"
        
        html = self._build_html_header(data.destinatario, div_texto)
        html += self._build_itens_section(data.itens)
        html += "<br>"
        html += self._build_footer(data_hoje, nome_daf, nome_dgmi, data.usos_daf, data.usos_dgmi)
        
        return html
    
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
    
    def _build_html_header(self, destinatario: str, div_texto: str) -> str:
        """Constrói o cabeçalho HTML."""
        return f"""
<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <title>Negativa - {destinatario}</title>
  <style>
    body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 40px; line-height: 1.6; color: #000000; }}
    h1 {{ text-align: center; text-decoration: underline; font-size: 17px; margin-bottom: 2px; color: #000000; }}
    h2 {{ text-align: center; font-size: 14px; margin: 2px 0; color: #000000; }}
    h3 {{ text-align: center; font-size: 14px; margin: 0; color: #000000; }}
    p {{ color: #000000; }}
    b {{ color: #000000; }}
    .content {{ margin: 30px 0; }}
    .assinaturas {{ display: flex; justify-content: center; align-items: flex-start; margin-top: 50px; gap: 60px; }}
    .assinatura {{ text-align: center; flex: 1; }}
    .assinatura strong {{ font-size: 11pt; color: #000000; }}
    .assinatura span {{ font-size: 10pt; font-weight: bold; color: #000000; }}
    .header {{ display: flex; align-items: center; justify-content: center; gap: 50px; margin-bottom: 10px; }}
    .header-title {{ text-align: center; text-decoration: underline; font-size: 17px; margin: 0; color: #000000; }}
    .divider {{ border-top: 1px solid #000000; margin: 20px 0; }}
    .brasao {{ display: block; height: {BRASAO_HEIGHT}px; }}
    @media print {{ body {{ margin: 0; }} }}
  </style>
</head>
<body>
  <div class="header">
    <img class="brasao" height="{BRASAO_HEIGHT}" src="data:image/svg+xml;base64,{svg_base64()}" alt="Brasão da Prefeitura">
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
        
        # Batch fetch medicamentos for CEAF items
        medicamentos_nomes = {item.nome for item in itens if item.categoria == "CEAF"}
        medicamentos_cache = {}
        for nome in medicamentos_nomes:
            med = self.db.get_medicamento_por_nome(nome)
            if med:
                medicamentos_cache[nome] = med
        
        html = ""
        for item in itens:
            html += self._build_item_html(item, medicamentos_cache)
        
        return html
    
    def _build_item_html(self, item: ItemSelecionado, medicamentos_cache: dict) -> str:
        """Constrói HTML para um item individual."""
        if item.categoria in ["CEAF", "USAFA", "CAPS II"]:
            return self._build_medicamento_html(item, medicamentos_cache)
        else:
            return self._build_nao_padronizado_html(item)
    
    def _build_medicamento_html(self, item: ItemSelecionado, medicamentos_cache: dict) -> str:
        """Constrói HTML para medicamentos padronizados."""
        modelo_obj = self.db.get_modelo_por_tipo(f"fornecimento_{item.categoria.lower()}")
        modelo_texto = modelo_obj.texto if modelo_obj else ""

        html = f"<p><b>{item.nome}</b>: {modelo_texto}"

        if item.categoria == "CEAF":
            med = medicamentos_cache.get(item.nome)
            if med and med.cids:
                prefix = "os CIDs de:" if len(med.cids) > 1 else "o CID de:"
                html += f" contemplando {prefix} {', '.join(med.cids)}."

        html += "</p>"

        if item.em_falta:
            modelo_falta = self.db.get_modelo_por_tipo("falta")
            if modelo_falta:
                html += f"<p>{modelo_falta.texto}</p>"

        return html
    
    def _build_nao_padronizado_html(self, item: ItemSelecionado) -> str:
        """Constrói HTML para itens não padronizados."""
        tipo_modelo = "nao_padronizado" if item.is_medicamento else "insumo_nao_padronizado"
        modelo_obj = self.db.get_modelo_por_tipo(tipo_modelo)
        if modelo_obj:
            return f"<p><b>{item.nome}</b>: {modelo_obj.texto}</p>"
        return ""
    
    def _build_footer(self, data_hoje: str, nome_daf: str, nome_dgmi: str, 
                      usos_daf: bool, usos_dgmi: bool) -> str:
        """Constrói o rodapé HTML com assinaturas."""
        html = f'    <p style="text-align: right">Praia Grande, {data_hoje}.</p>'
        html += '    <p style="text-align: right">Atenciosamente,</p>'
        html += '    <div class="assinaturas">'

        if usos_daf:
            html += f'''
      <div class="assinatura">
        <br><br>
        <strong>{nome_daf}</strong><br>
        <strong>DIVISÃO DE ASSISTÊNCIA FARMACÊUTICA</strong><br>
        <span>SESAP 10.2.02</span>
      </div>'''

        if usos_dgmi:
            html += f'''
      <div class="assinatura">
        <br><br>
        <strong>{nome_dgmi}</strong><br>
        <strong>DIVISÃO DE GESTÃO DE MATERIAIS E INSUMOS</strong><br>
        <span>SESAP 10.6.1.3</span>
      </div>'''

        html += '    </div>'
        html += '  </div></body></html>'
        return html
