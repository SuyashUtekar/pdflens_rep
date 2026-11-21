from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _load_env_file() -> None:
    """Load simple KEY=value settings from the project .env without overriding real env vars."""
    env_file = Path(os.getenv("PDFLENS_ENV_FILE", ".env"))
    if not env_file.is_absolute():
        env_file = Path(__file__).resolve().parents[1] / env_file
    if not env_file.is_file():
        return
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if not key or key in os.environ:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value


_load_env_file()


def _parse_configs(value: str) -> tuple[dict[str, str], ...]:
    if not value.strip():
        return ()
    try:
        raw: Any = json.loads(value)
    except json.JSONDecodeError as exc:
        raise RuntimeError("PDFLENS_CONFIGS_JSON must be a JSON array of {id, label} objects.") from exc
    if not isinstance(raw, list):
        raise RuntimeError("PDFLENS_CONFIGS_JSON must be a JSON array.")
    configs: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise RuntimeError("Each PDFLens config entry must contain an id and label.")
        config_id = str(item.get("id", "")).strip()
        label = str(item.get("label", "")).strip()
        if not config_id or not label or config_id in seen:
            raise RuntimeError("Each PDFLens config needs a unique id and a non-empty label.")
        seen.add(config_id)
        configs.append({"id": config_id, "label": label})
    return tuple(configs)


@dataclass(frozen=True)
class Settings:
    submit_url: str = os.getenv("PDFLENS_API_SUBMIT_URL", "").strip()
    result_url: str = os.getenv("PDFLENS_API_RESULT_URL", "").strip()
    health_url: str = os.getenv("PDFLENS_API_HEALTH_URL", "").strip()
    result_method: str = os.getenv("PDFLENS_API_RESULT_METHOD", "POST").strip().upper()
    health_method: str = os.getenv("PDFLENS_API_HEALTH_METHOD", "GET").strip().upper()
    jwt_token: str = os.getenv("PDFLENS_JWT_TOKEN", "").strip()
    jwt_header: str = os.getenv(
        "PDFLENS_JWT_HEADER", os.getenv("PDFLENS_API_KEY_HEADER", "Authorization")
    ).strip()
    jwt_prefix: str = os.getenv(
        "PDFLENS_JWT_PREFIX", os.getenv("PDFLENS_API_KEY_PREFIX", "Bearer")
    ).strip()
    api_key: str = os.getenv("PDFLENS_API_KEY", "").strip()
    timeout_seconds: float = float(os.getenv("PDFLENS_API_TIMEOUT_SECONDS", "180"))
    result_poll_interval_seconds: float = float(os.getenv("PDFLENS_RESULT_POLL_INTERVAL_SECONDS", "5"))
    result_poll_max_wait_seconds: int = int(os.getenv("PDFLENS_RESULT_POLL_MAX_WAIT_SECONDS", "900"))
    callback_url: str = os.getenv("PDFLENS_CALLBACK_URL", "").strip()
    shared_storage_dir: Path = Path(os.getenv("PDFLENS_SHARED_STORAGE_DIR", "./data/pdflens-shared"))
    staging_directory_mode: int = int(os.getenv("PDFLENS_STAGING_DIRECTORY_MODE", "750"), 8)
    staging_file_mode: int = int(os.getenv("PDFLENS_STAGING_FILE_MODE", "640"), 8)
    staging_retention_hours: int = int(os.getenv("PDFLENS_STAGING_RETENTION_HOURS", "168"))
    max_result_bytes: int = int(os.getenv("PDFLENS_MAX_RESULT_ZIP_BYTES", str(500 * 1024 * 1024)))
    configs: tuple[dict[str, str], ...] = _parse_configs(os.getenv("PDFLENS_CONFIGS_JSON", ""))

    def __post_init__(self) -> None:
        if self.result_poll_interval_seconds < 1:
            raise RuntimeError("PDFLENS_RESULT_POLL_INTERVAL_SECONDS must be at least 1 second.")
        if not 1 <= self.result_poll_max_wait_seconds <= 86400:
            raise RuntimeError("PDFLENS_RESULT_POLL_MAX_WAIT_SECONDS must be between 1 and 86400 seconds.")

    @property
    def auth_token(self) -> str:
        """Prefer a JWT, while accepting the older API-key variable as a fallback."""
        return self.jwt_token or self.api_key


settings = Settings()
