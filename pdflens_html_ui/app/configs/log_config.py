from __future__ import annotations

import logging

from app.constants.app_constants import app_config

log_path = str(app_config.LOG_PATH)


class EnterpriseContextFilter(logging.Filter):
    """Provide defaults required by the enterprise formatter for every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        defaults = {
            "remote_address": "-",
            "remote_host": "-",
            "remote_port": "-",
            "host_name": "-",
            "principal": "-",
            "correlation_id": "-",
            "service_name": app_config.APP_NAME,
            "event_name": record.getMessage().split(" ", 1)[0],
            "event_id": "-",
            "event_description": record.getMessage(),
            "function": record.funcName,
        }
        for key, value in defaults.items():
            if not hasattr(record, key):
                setattr(record, key, value)
        return True


LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "enterpriseContext": {
            "()": "app.configs.log_config.EnterpriseContextFilter",
        },
    },
    "formatters": {
        "standardFormatter": {
            "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
        "enterpriseFormatter": {
            "format": (
                "EVENT_DATE_TIME=%(asctime)s|REMOTE_ADDRESS=%(remote_address)s|"
                "REMOTE_HOST=%(remote_host)s|REMOTE_PORT=%(remote_port)s|"
                "HOST_NAME=%(host_name)s|PRINCIPAL=%(principal)s|"
                "CORRELATION_ID=%(correlation_id)s|SERVICE_NAME=%(service_name)s|"
                "EVENT_NAME=%(event_name)s|EVENT_ID=%(event_id)s|"
                "EVENT_DESCRIPTION=%(event_description)s|FUNCTION_NAME=%(function)s|"
                "LOG_LEVEL=%(levelname)s|LOG_CLASS=%(name)s|%(message)s"
            ),
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },
    "handlers": {
        "consoleHandler": {
            "class": "logging.StreamHandler",
            "level": app_config.LOG_LEVEL,
            "formatter": "standardFormatter",
            "filters": ["enterpriseContext"],
            "stream": "ext://sys.stdout",
        },
        "knowledgeFileHandler": {
            "class": "logging.handlers.TimedRotatingFileHandler",
            "level": app_config.LOG_LEVEL,
            "formatter": "standardFormatter",
            "filename": log_path,
            "when": "midnight",
            "interval": 1,
            "backupCount": 14,
            "encoding": "utf8",
            "filters": ["enterpriseContext"],
        },
    },
    "loggers": {
        app_config.APP_NAME: {
            "handlers": ["knowledgeFileHandler", "consoleHandler"],
            "level": app_config.LOG_LEVEL,
            "propagate": False,
        },
    },
    "root": {
        "handlers": ["consoleHandler"],
        "level": app_config.LOG_LEVEL,
    },
}
