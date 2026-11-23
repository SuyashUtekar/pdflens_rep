from __future__ import annotations

import os
import logging
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppConfig:
    APP_NAME: str = os.getenv("APP_NAME", "pdflens")
    LOG_PATH: Path = Path(os.getenv("LOG_PATH", "logs/pdflens.log")).expanduser()
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").strip().upper()

    def __post_init__(self) -> None:
        if not isinstance(getattr(logging, self.LOG_LEVEL, None), int):
            object.__setattr__(self, "LOG_LEVEL", "INFO")


app_config = AppConfig()
