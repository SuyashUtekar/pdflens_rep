from __future__ import annotations

import logging
import logging.config
import re
import socket
import uuid
from pathlib import Path
from typing import Any

from app.configs.log_config import LOGGING_CONFIG
from app.constants.app_constants import app_config

_config_applied = False
_SENSITIVE_KEYS = ("token", "authorization", "password", "secret", "api_key", "credential")
_WHITESPACE = re.compile(r"\s+")


def get_app_logger() -> logging.Logger:
    """Configure application logging once and return the shared application logger."""
    global _config_applied
    if not _config_applied:
        Path(app_config.LOG_PATH).parent.mkdir(parents=True, exist_ok=True)
        logging.config.dictConfig(LOGGING_CONFIG)
        _config_applied = True
    return logging.getLogger(app_config.APP_NAME)


def log_event(logger: logging.Logger, level: int, event: str, **fields: Any) -> None:
    """Write a compact event record and redact fields that look like credentials."""
    parts = [event]
    extra: dict[str, Any] = {
        "event_name": event,
        "event_id": uuid.uuid4().hex,
        "service_name": app_config.APP_NAME,
        "correlation_id": fields.get("request_id", "-"),
        "host_name": socket.gethostname(),
    }
    for key, value in fields.items():
        if any(sensitive in key.casefold() for sensitive in _SENSITIVE_KEYS):
            rendered = "[REDACTED]"
        elif value is None:
            rendered = "none"
        else:
            rendered = _WHITESPACE.sub("_", str(value)).replace("\x00", "")
        parts.append(f"{key}={rendered}")
    extra["event_description"] = " ".join(parts)
    caller = logging.currentframe()
    if caller is not None:
        caller = caller.f_back
        if caller is not None and caller.f_code.co_name in {"info", "warning", "error"}:
            caller = caller.f_back
        if caller is not None:
            extra["function"] = caller.f_code.co_name
    logger.log(level, " ".join(parts), extra=extra)


def info(logger: logging.Logger, event: str, **fields: Any) -> None:
    log_event(logger, logging.INFO, event, **fields)


def warning(logger: logging.Logger, event: str, **fields: Any) -> None:
    log_event(logger, logging.WARNING, event, **fields)


def error(logger: logging.Logger, event: str, **fields: Any) -> None:
    log_event(logger, logging.ERROR, event, **fields)
