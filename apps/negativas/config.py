from dataclasses import dataclass, field
from typing import Any
from pathlib import Path

from andaime.paths import get_config_path


@dataclass
class NegativasConfig:
    """Configurações do aplicativo."""
    theme: str = "light"
    nome_daf: str = ""
    nome_dgmi: str = ""

    @classmethod
    def get_defaults(cls) -> "NegativasConfig":
        return cls()

    def to_dict(self) -> dict[str, Any]:
        return {
            "theme": self.theme,
            "nome_daf": self.nome_daf,
            "nome_dgmi": self.nome_dgmi,
        }

    @classmethod
    def migrate_data(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Migra dados antigos para o formato atual."""
        # Remove campos não usados
        data.pop("usar_daf", None)
        data.pop("usar_dgmi", None)
        return data

    @staticmethod
    def get_config_path() -> Path:
        return get_config_path()