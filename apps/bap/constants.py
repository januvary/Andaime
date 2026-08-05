from enum import Enum


class Status(str, Enum):
    """Status canônico de um processo (chave armazenada no banco)."""

    EM_ANALISE = "em_analise"
    INCOMPLETO = "incompleto"
    COMPLETO = "completo"
    ENVIADO = "enviado"
    CORRECAO = "correcao"
    AUTORIZADO = "autorizado"
    EXPIRADO = "expirado"
    NEGADO = "negado"
    ENCERRADO = "encerrado"


TIPO_LABELS = {
    "medicamento": "Medicamento",
    "nutricao": "Nutrição",
    "bomba": "Bomba de Insulina",
}

# Rótulo curto em maiúsculas (estilo planilha / nome de pasta).
TIPO_UPPER = {
    "medicamento": "MEDICAMENTO",
    "nutricao": "NUTRIÇÃO",
    "bomba": "BOMBA",
}

TIPO_HEX = {
    "medicamento": "#3B82F6",
    "nutricao": "#10B981",
    "bomba": "#F59E0B",
}

SOLICITACAO_LABELS = {
    "primeira": "1ª Solicitação",
    "renovacao": "Renovação",
}

STATUS_LABELS = {
    Status.EM_ANALISE: "Em Análise",
    Status.INCOMPLETO: "Incompleto",
    Status.COMPLETO: "Completo",
    Status.ENVIADO: "Enviado",
    Status.CORRECAO: "Correção",
    Status.AUTORIZADO: "Autorizado",
    Status.EXPIRADO: "Expirado",
    Status.NEGADO: "Negado",
    Status.ENCERRADO: "Encerrado",
}

# Transições de status permitidas (máquina de estados). Além do que está
# aqui, ``allowed_status_transitions`` aplica duas regras universais:
#   - um status nulo/vazio pode mudar para qualquer status;
#   - qualquer status pode mudar para "encerrado".
# ``NULL_STATUS`` é um sentinel para a opção "sem status" (limpar o status),
# usada para fechar o ciclo (encerrado -> nulo).
NULL_STATUS = "__null__"
NULL_STATUS_LABEL = "Nenhum"

STATUS_TRANSITIONS = {
    Status.EM_ANALISE: [Status.INCOMPLETO, Status.COMPLETO],
    Status.INCOMPLETO: [Status.COMPLETO],
    Status.COMPLETO: [Status.ENVIADO, Status.INCOMPLETO],
    Status.ENVIADO: [Status.CORRECAO, Status.AUTORIZADO, Status.NEGADO],
    Status.CORRECAO: [Status.ENVIADO, Status.AUTORIZADO, Status.NEGADO],
    Status.AUTORIZADO: [Status.EXPIRADO],
    Status.EXPIRADO: [],
    Status.NEGADO: [],
    Status.ENCERRADO: [NULL_STATUS],
}


def status_display_label(key: str | None) -> str:
    """Rótulo de exibição de um status, tratando nulo/sentinel como "Nenhum"."""
    if not key or key == NULL_STATUS:
        return NULL_STATUS_LABEL
    return STATUS_LABELS.get(key, key)


def allowed_status_transitions(current: str | None) -> list[str]:
    """Retorna as chaves de status para as quais ``current`` pode mudar.

    - status nulo/vazio pode ir para qualquer status;
    - qualquer status (exceto ele mesmo) pode ir para ``encerrado``;
    - ``encerrado`` pode voltar para nulo (``NULL_STATUS``), fechando o ciclo.

    O resultado segue a ordem de ``STATUS_LABELS`` (com ``encerrado`` ao fim).
    """
    if not current or current == NULL_STATUS:
        return list(STATUS_LABELS.keys())
    allowed = STATUS_TRANSITIONS.get(current, [])
    result = [k for k in STATUS_LABELS if k in allowed]
    if NULL_STATUS in allowed:
        result.append(NULL_STATUS)
    if current != Status.ENCERRADO:
        result.append(Status.ENCERRADO)
    return result

# Cores do status — seguem o padrão do Emissor: tons neutros de cinza
# mais as três cores semânticas (success/warning/error). Cada status é
# mapeado para uma chave da paleta do tema (``andaime.qt.theme.colors``),
# resolvida em tempo de execução para se adaptar a ambos os temas.
STATUS_SEMANTIC = {
    Status.EM_ANALISE: "text_dim",       # em andamento (neutro)
    Status.INCOMPLETO: "status_warning",  # requer atenção
    Status.COMPLETO: "status_success",    # pronto para envio
    Status.ENVIADO: "text",               # enviado ao DRS (neutro forte)
    Status.CORRECAO: "status_warning",    # retornou com pendências
    Status.AUTORIZADO: "status_success",  # deferido
    Status.EXPIRADO: "status_warning",    # autorização expirada, requer renovação
    Status.NEGADO: "status_error",        # indeferido
    Status.ENCERRADO: "text_dim",         # arquivado (neutro)
}

DOC_TYPE_LABELS = {
    "formulario": "Formulário de Avaliação",
    "declaracao": "Declaração de Conflito de Interesses",
    "receita": "Receita Médica",
    "relatorio": "Relatório Médico",
    "exame": "Exames Complementares",
    "documento_pessoal": "Documentos Pessoais",
    "outro": "Outro",
}

DOC_TYPE_ORDER = {
    "formulario": 1,
    "declaracao": 2,
    "receita": 3,
    "relatorio": 4,
    "exame": 5,
    "documento_pessoal": 6,
    "outro": 7,
}

RENOVACAO_DOC_EXCLUSIONS = {"documento_pessoal"}

# Colunas da tabela de processos da página de Remessas.
REMESSA_COLUMNS = [
    "Paciente",
    "Tipo",
    "Descrição",
    "Observações",
    "Status",
    "Telefone",
]

WHATSAPP_TEMPLATES = {
    "completo": "Seu processo ({protocolo}) está completo e será enviado ao DRS na remessa de {date}.",
    "enviado": "Seu processo ({protocolo}) foi enviado ao DRS em {date}. Prazo de resposta: 30-60 dias.",
    "correcao": "Seu processo ({protocolo}) retornou do DRS com pendências: {observacoes}.",
    "autorizado": "Seu processo ({protocolo}) foi AUTORIZADO. Retirada na DRS Santos.",
    "negado": "Seu processo ({protocolo}) foi NEGADO. Justificativa: {observacoes}.",
}
