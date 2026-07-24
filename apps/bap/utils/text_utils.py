from andaime.text import to_upper_normalized


def fold_diacritics(s: str) -> str:
    """Remove acentos/diacríticos: NFKD + strip combining marks."""
    import unicodedata

    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def generate_initials(nome: str, max_chars: int = 4) -> str:
    parts = to_upper_normalized(nome).split()
    if not parts:
        return "XXXX"
    return "".join(p[0] for p in parts[:max_chars])


def generate_protocolo(lote_date: str, initials: str, seq: int) -> str:
    return f"{lote_date}-{initials}-{seq:02d}"


def normalize_phone(raw: str | None) -> str:
    """Normaliza um telefone para apenas dígitos (formato de armazenamento).

    - Remove qualquer caractere não numérico.
    - Remove o código do país (55) quando presente.
    - Se houver mais de um número no mesmo campo, usa o primeiro.
    - Retorna "" quando o valor não parece um telefone válido
      (menos de 10 dígitos, ex.: anotações como "Avisado a Erika.").

    Telefones brasileiros válidos têm 10 (fixo com DDD) ou 11 (celular
    com DDD) dígitos.
    """
    if not raw:
        return ""
    digits = _digits(raw)
    if not digits:
        return ""
    # Remove código do país (55) em números com 12/13 dígitos.
    if len(digits) >= 12 and digits.startswith("55"):
        digits = digits[2:]
    # Campo com múltiplos números: usa apenas o primeiro.
    if len(digits) > 11:
        digits = digits[:11]
    if len(digits) < 10:
        return ""
    return digits


def _digits(value: str | None, limit: int | None = None) -> str:
    d = "".join(ch for ch in str(value or "") if ch.isdigit())
    return d[:limit] if limit is not None else d


def _mask_complete(d: str) -> str:
    """Aplica a máscara de um telefone completo (10 ou 11 dígitos)."""
    if len(d) == 11:
        return f"{d[:2]} {d[2:7]}-{d[7:]}"
    if len(d) == 10:
        return f"{d[:2]} {d[2:6]}-{d[6:]}"
    return d


def format_phone(value: str | None) -> str:
    """Formata um telefone (dígitos) para exibição.

    - 11 dígitos: ``XX XXXXX-XXXX`` (celular)
    - 10 dígitos: ``XX XXXX-XXXX`` (fixo)
    Caso não corresponda, retorna o valor original sem alteração.
    """
    if not value:
        return ""
    d = _digits(value)
    if len(d) in (10, 11):
        return _mask_complete(d)
    return value


def format_phone_live(text: str | None) -> str:
    """Formata um telefone parcialmente, à medida que é digitado.

    Aplica a máscara progressivamente conforme os dígitos são inseridos,
    limitando a 11 dígitos (padrão brasileiro com DDD):

    - até 2 dígitos:  ``XX``
    - 3 a 6 dígitos:  ``XX XXXX``
    - 7 a 10 dígitos: ``XX XXXX-XXXX`` (fixo)
    - 11 dígitos:     ``XX XXXXX-XXXX`` (celular)
    """
    if not text:
        return ""
    d = _digits(text, limit=11)
    n = len(d)
    if n == 0:
        return ""
    if n <= 2:
        return d
    if n <= 6:
        return f"{d[:2]} {d[2:]}"
    if n <= 10:
        return f"{d[:2]} {d[2:6]}-{d[6:]}"
    return _mask_complete(d)
