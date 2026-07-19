from andaime.dates import parse_date, format_date


def format_date_display(date_str: str) -> str:
    """Formata uma data (ISO ou qualquer formato parseável) para exibição.

    Retorna a data formatada quando o parse sucede, ou a string original
    (ou vazia) como *fallback* — nunca levanta.
    """
    d = parse_date(date_str)
    return format_date(d) if d else (date_str or "")
