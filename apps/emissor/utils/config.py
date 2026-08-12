#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Configuration Management — AppConfig (específico do Emissor)."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from andaime.paths import get_root_directory
from andaime.error_handler import ErrorContext, ErrorHandler, ErrorLevel


@dataclass
class OlostechConfig:
    """Configuração de integração com a plataforma Olostech."""

    username: str = ""
    password: str = ""
    lst_acesso: str = ""
    unit: str = ""
    environment: str = ""
    role: str = ""
    aceite_chave: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "username": self.username,
            "password": self.password,
            "lst_acesso": self.lst_acesso,
            "unit": self.unit,
            "environment": self.environment,
            "role": self.role,
            "aceite_chave": self.aceite_chave,
        }

    @staticmethod
    def from_dict(data: dict[str, Any] | None) -> "OlostechConfig":
        if not data:
            return OlostechConfig()
        return OlostechConfig(
            username=data.get("username", ""),
            password=data.get("password", ""),
            lst_acesso=data.get("lst_acesso", ""),
            unit=data.get("unit", ""),
            environment=data.get("environment", ""),
            role=data.get("role", ""),
            aceite_chave=data.get("aceite_chave", ""),
        )


@dataclass
class AppConfig:
    """Configuração da aplicação com validação."""

    save_location: Path | str
    print_copies: int = 2
    dark_mode: bool = True
    distribute_retiradas: bool = True
    distribution_window_days: int = 3
    scan_dpi: int = 200
    scan_color_mode: str = "grayscale"
    olostech: OlostechConfig = field(default_factory=OlostechConfig)

    _VALID_COLOR_MODES: tuple[str, ...] = ("grayscale", "color", "bw")

    def __post_init__(self) -> None:
        if isinstance(self.olostech, dict):
            self.olostech = OlostechConfig.from_dict(self.olostech)
        self.validate()

    def validate(self) -> None:
        if not isinstance(self.print_copies, int):
            raise ValueError(
                f"print_copies must be int, got {type(self.print_copies).__name__}"
            )
        if not 1 <= self.print_copies <= 4:
            raise ValueError(f"print_copies must be 1-4, got {self.print_copies}")

        if not isinstance(self.dark_mode, bool):
            raise ValueError(
                f"dark_mode must be bool, got {type(self.dark_mode).__name__}"
            )

        if not isinstance(self.distribute_retiradas, bool):
            raise ValueError(
                f"distribute_retiradas must be bool, got {type(self.distribute_retiradas).__name__}"
            )

        if not isinstance(self.distribution_window_days, int):
            raise ValueError(
                f"distribution_window_days must be int, got {type(self.distribution_window_days).__name__}"
            )
        if not 1 <= self.distribution_window_days <= 7:
            raise ValueError(
                f"distribution_window_days must be 1-7, got {self.distribution_window_days}"
            )

        if isinstance(self.save_location, str):
            self.save_location = Path(self.save_location)

        if not self.save_location.exists():
            raise ValueError(f"save_location does not exist: {self.save_location}")

        if not isinstance(self.scan_dpi, int):
            raise ValueError(
                f"scan_dpi must be int, got {type(self.scan_dpi).__name__}"
            )
        if not 50 <= self.scan_dpi <= 1200:
            raise ValueError(f"scan_dpi must be 50-1200, got {self.scan_dpi}")

        if not isinstance(self.scan_color_mode, str):
            raise ValueError(
                f"scan_color_mode must be str, got {type(self.scan_color_mode).__name__}"
            )
        if self.scan_color_mode not in self._VALID_COLOR_MODES:
            raise ValueError(
                f"scan_color_mode must be one of {self._VALID_COLOR_MODES}, "
                f"got {self.scan_color_mode}"
            )

    def to_dict(self) -> dict:
        return {
            "save_location": str(self.save_location),
            "print_copies": self.print_copies,
            "dark_mode": self.dark_mode,
            "distribute_retiradas": self.distribute_retiradas,
            "distribution_window_days": self.distribution_window_days,
            "scan_dpi": self.scan_dpi,
            "scan_color_mode": self.scan_color_mode,
            "olostech": self.olostech.to_dict(),
        }

    @staticmethod
    def get_defaults() -> "AppConfig":
        return AppConfig(
            save_location=get_root_directory(),
            print_copies=2,
            dark_mode=True,
            distribute_retiradas=True,
            distribution_window_days=3,
            scan_dpi=200,
            scan_color_mode="grayscale",
            olostech=OlostechConfig(),
        )

    @staticmethod
    def migrate_data(data: dict) -> dict:
        if "force_single_page" in data:
            del data["force_single_page"]
            ErrorHandler.log(
                "Removido 'force_single_page' legado do config",
                level=ErrorLevel.INFO,
                context=ErrorContext.CONFIGURATION,
            )
        if "archive_folder_name" in data:
            del data["archive_folder_name"]
            ErrorHandler.log(
                "Removido 'archive_folder_name' legado do config",
                level=ErrorLevel.INFO,
                context=ErrorContext.CONFIGURATION,
            )
        return data
