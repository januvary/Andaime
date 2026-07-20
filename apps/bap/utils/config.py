from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from andaime.paths import get_root_directory


def bap_data_dir() -> Path:
    """Diretório de dados do BAP: <root>/data (dentro da pasta do app)."""
    d = get_root_directory() / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass
class SS54Config:
    theme: str = "dark"
    drs_renovacao_email: str = ""
    drs_solicitacao_email: str = ""
    operator_email: str = ""
    gmail_credentials_path: str = ""
    gmail_token_path: str = ""
    last_lote_id: Optional[int] = None
    arquivos_root: str = ""

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        if self.theme not in ("dark", "light"):
            raise ValueError(f"theme must be 'dark' or 'light', got {self.theme}")

        if not isinstance(self.drs_renovacao_email, str):
            raise ValueError(
                f"drs_renovacao_email must be str, got {type(self.drs_renovacao_email).__name__}"
            )

        if not isinstance(self.drs_solicitacao_email, str):
            raise ValueError(
                f"drs_solicitacao_email must be str, got {type(self.drs_solicitacao_email).__name__}"
            )

        if not isinstance(self.operator_email, str):
            raise ValueError(
                f"operator_email must be str, got {type(self.operator_email).__name__}"
            )

        if not isinstance(self.gmail_credentials_path, str):
            raise ValueError(
                f"gmail_credentials_path must be str, got {type(self.gmail_credentials_path).__name__}"
            )

        if not isinstance(self.gmail_token_path, str):
            raise ValueError(
                f"gmail_token_path must be str, got {type(self.gmail_token_path).__name__}"
            )

    def to_dict(self) -> dict:
        return {
            "theme": self.theme,
            "drs_renovacao_email": self.drs_renovacao_email,
            "drs_solicitacao_email": self.drs_solicitacao_email,
            "operator_email": self.operator_email,
            "gmail_credentials_path": self.gmail_credentials_path,
            "gmail_token_path": self.gmail_token_path,
            "last_lote_id": self.last_lote_id,
            "arquivos_root": self.arquivos_root,
        }

    @staticmethod
    def get_defaults() -> "SS54Config":
        return SS54Config()
