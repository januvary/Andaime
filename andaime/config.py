"""
Generic configuration manager.

The app provides a dataclass with:
  - to_dict() -> dict
  - get_defaults() -> <dataclass>
  - __post_init__ validation
  - Optional: migrate_data(data: dict) -> dict for JSON migrations
"""

from __future__ import annotations

import json
from dataclasses import fields, replace
from typing import Any

from andaime.paths import get_config_path
from andaime.error_handler import ErrorHandler, ErrorLevel


class ConfigManager:
    _instance: ConfigManager | None = None
    _config: Any = None
    _config_cls: type | None = None

    def __new__(cls) -> ConfigManager:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def init(cls, config_cls: type) -> None:
        cls._config_cls = config_cls

    def __init__(self) -> None:
        if type(self)._config is None:
            type(self)._load()

    @classmethod
    def _load(cls) -> Any:
        config_cls = cls._config_cls
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
                cls._config = config
                return config

            except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
                ErrorHandler.log(
                    f"Configuração inválida: {e}. Usando padrão",
                    level=ErrorLevel.WARNING,
                    context="Configuration",
                )
                cls._config = config_cls.get_defaults()
                cls._save_to_file(cls._config)
                return cls._config
        else:
            config = config_cls.get_defaults()
            cls._save_to_file(config)
            cls._config = config
            return config

    @classmethod
    def _save_to_file(cls, config: Any) -> None:
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
        if type(self)._config is None:
            type(self)._load()

        try:
            return getattr(type(self)._config, key)
        except AttributeError:
            return default

    def set(self, key: str, value: Any) -> bool:
        if type(self)._config is None:
            type(self)._load()

        config_cls = type(self)._config_cls
        if config_cls is None:
            return False

        valid_fields = {f.name for f in fields(config_cls)}
        if key not in valid_fields:
            return False

        try:
            candidate = replace(type(self)._config, **{key: value})
            type(self)._config = candidate
            type(self)._save_to_file(type(self)._config)
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
        if type(self)._config is None:
            type(self)._load()
        return type(self)._config

    def reload(self) -> None:
        type(self)._config = None
        type(self)._load()

    def reset_to_defaults(self) -> None:
        config_cls = type(self)._config_cls
        if config_cls is None:
            return
        type(self)._config = config_cls.get_defaults()
        type(self)._save_to_file(type(self)._config)

    @classmethod
    def _reset(cls) -> None:
        cls._instance = None
        cls._config = None
