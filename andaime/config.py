"""
Generic configuration manager.

The app provides a dataclass with:
  - to_dict() -> dict
  - get_defaults() -> <dataclass>
  - __post_init__ validation
  - Optional: migrate_data(data: dict) -> dict for JSON migrations
"""

from __future__ import annotations

import copy
import json
from dataclasses import fields, replace
from pathlib import Path
from typing import Any, Optional, Type

from andaime.paths import get_config_path
from andaime.error_handler import ErrorHandler, ErrorLevel


class ConfigManager:
    _instance: Optional["ConfigManager"] = None
    _config: Any = None
    _config_cls: Optional[Type] = None

    def __new__(cls) -> "ConfigManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def init(cls, config_cls: Type) -> None:
        cls._config_cls = config_cls

    def __init__(self) -> None:
        if self._config is None:
            self._load()

    @staticmethod
    def _load() -> Any:
        config_cls = ConfigManager._config_cls
        if config_cls is None:
            raise RuntimeError("ConfigManager.init(config_cls) must be called first")

        config_file = get_config_path()

        if config_file.exists():
            try:
                with config_file.open("r", encoding="utf-8") as f:
                    data = json.load(f)

                migrate = getattr(config_cls, "migrate_data", None)
                if migrate:
                    data = migrate(data)

                config = config_cls(**data)
                ErrorHandler.log(
                    f"Configuração carregada: {config_file}",
                    level=ErrorLevel.INFO,
                    context="Configuration",
                )
                ConfigManager._config = config
                return config

            except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
                ErrorHandler.log(
                    f"Configuração inválida: {e}. Usando padrão",
                    level=ErrorLevel.WARNING,
                    context="Configuration",
                )
                ConfigManager._config = config_cls.get_defaults()
                ConfigManager._save_to_file(ConfigManager._config)
                return ConfigManager._config
        else:
            config = config_cls.get_defaults()
            ConfigManager._save_to_file(config)
            ConfigManager._config = config
            return config

    @staticmethod
    def _save_to_file(config: Any) -> None:
        try:
            config_file = get_config_path()
            config_file.parent.mkdir(parents=True, exist_ok=True)

            with config_file.open("w", encoding="utf-8") as f:
                json.dump(config.to_dict(), f, indent=2, ensure_ascii=False)

            ErrorHandler.log(
                f"Configuração salva: {config_file}",
                level=ErrorLevel.INFO,
                context="Configuration",
            )
        except Exception as e:
            ErrorHandler.handle_error(
                e,
                context="Configuration",
                recovery_hint="Verifique permissões de escrita",
                show_dialog=False,
            )

    def get(self, key: str, default: Any = None) -> Any:
        if self._config is None:
            self._config = self._load()

        try:
            return getattr(self._config, key)
        except AttributeError:
            return default

    def set(self, key: str, value: Any) -> bool:
        if self._config is None:
            self._config = self._load()

        config_cls = self._config_cls
        if config_cls is None:
            return False

        valid_fields = {f.name for f in fields(config_cls)}
        if key not in valid_fields:
            return False

        try:
            candidate = replace(self._config, **{key: value})
            self._config = candidate
            self._save_to_file(self._config)
            return True
        except (ValueError, TypeError):
            return False
        except Exception as e:
            ErrorHandler.log(
                f"Falha ao atualizar config: {e}",
                level=ErrorLevel.ERROR,
                context="Configuration",
            )
            return False

    def get_all(self) -> Any:
        if self._config is None:
            self._config = self._load()
        return self._config

    def reload(self) -> None:
        self._config = None
        self._load()

    def reset_to_defaults(self) -> None:
        config_cls = self._config_cls
        if config_cls is None:
            return
        self._config = config_cls.get_defaults()
        self._save_to_file(self._config)

    @classmethod
    def _reset(cls) -> None:
        cls._instance = None
        cls._config = None
