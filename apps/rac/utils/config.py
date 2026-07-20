from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class RACConfig:
    stay_on_page: bool = False
    theme: str = "dark"
    last_malote_id: Optional[int] = None
    save_path: Optional[Path] = None
    usafa_id: str = "ocian"
    usafa_name: str = "USAFA OCIAN"

    def __post_init__(self) -> None:
        if self.save_path is None:
            self.save_path = Path.home() / "Downloads"
        if isinstance(self.save_path, str):
            self.save_path = Path(self.save_path)
        self.validate()

    def validate(self) -> None:
        if not isinstance(self.stay_on_page, bool):
            raise ValueError(
                f"stay_on_page must be bool, got {type(self.stay_on_page).__name__}"
            )

        if self.theme not in ("dark", "light"):
            raise ValueError(f"theme must be 'dark' or 'light', got {self.theme}")

        if self.last_malote_id is not None and not isinstance(self.last_malote_id, int):
            raise ValueError(
                f"last_malote_id must be int or None, got {type(self.last_malote_id).__name__}"
            )

        if not isinstance(self.usafa_id, str) or not self.usafa_id.strip():
            raise ValueError("usafa_id must be a non-empty string")

        if not isinstance(self.usafa_name, str) or not self.usafa_name.strip():
            raise ValueError("usafa_name must be a non-empty string")

    def to_dict(self) -> dict:
        return {
            "stay_on_page": self.stay_on_page,
            "theme": self.theme,
            "last_malote_id": self.last_malote_id,
            "save_path": str(self.save_path),
            "usafa_id": self.usafa_id,
            "usafa_name": self.usafa_name,
        }

    @staticmethod
    def get_defaults() -> "RACConfig":
        return RACConfig(
            stay_on_page=False,
            theme="dark",
            last_malote_id=None,
            save_path=Path.home() / "Downloads",
            usafa_id="ocian",
            usafa_name="USAFA OCIAN",
        )

    @staticmethod
    def migrate_data(data: dict) -> dict:
        if "auto_return" in data and "stay_on_page" not in data:
            data["stay_on_page"] = not data.pop("auto_return")
        return data
