"""Structured JSON logging — stdout only, capturado por docker-compose y Cloud Logging.

conversation_id_var permite correlacionar logs entre api.py, orchestrator.py,
query_cv.py y query_github.py sin pasar conversation_id como parámetro explícito
por toda la cadena de llamadas (ver ContextVar).
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import sys
from datetime import datetime, timezone

conversation_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "conversation_id", default=None
)

_RESERVED_RECORD_KEYS = frozenset(logging.makeLogRecord({}).__dict__)


class ConversationIdFilter(logging.Filter):
    """Inyecta el conversation_id actual (si existe) en cada LogRecord."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.conversation_id = conversation_id_var.get()
        return True


def _extract_extra(record: logging.LogRecord) -> dict:
    """Campos pasados vía extra={...} en cada logger.info/warning/error(...) call."""
    return {
        k: v
        for k, v in record.__dict__.items()
        if k not in _RESERVED_RECORD_KEYS and k != "conversation_id"
    }


class JsonFormatter(logging.Formatter):
    """Una línea JSON por log — Cloud Logging la parsea automáticamente como jsonPayload."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
            "conversation_id": getattr(record, "conversation_id", None),
        }
        payload.update(_extract_extra(record))
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


_LEVEL_ABBREV = {"DEBUG": "DBG", "INFO": "INF", "WARNING": "WRN", "ERROR": "ERR", "CRITICAL": "CRT"}


class ConsoleFormatter(logging.Formatter):
    """Una línea legible para terminal local. No usar en Cloud Run (ahí queremos JSON)."""

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).strftime("%H:%M:%S.%f")[:-3]
        level = _LEVEL_ABBREV.get(record.levelname, record.levelname[:3])
        conv = getattr(record, "conversation_id", None)
        conv_tag = f"[{conv[:8]}]" if conv else "[--------]"
        fields = " ".join(f"{k}={v}" for k, v in _extract_extra(record).items())
        line = f"{ts} {level} {conv_tag} {record.name:<20} {record.getMessage():<22} {fields}".rstrip()
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


_configured = False


def setup_logging() -> None:
    """Configura el root logger una sola vez. Idempotente — llamar libremente.

    LOG_FORMAT=console da salida legible para desarrollo local (default: json,
    requerido para que Cloud Logging parsee los campos en producción).
    """
    global _configured
    if _configured:
        return

    fmt = os.environ.get("LOG_FORMAT", "json").lower()
    formatter = ConsoleFormatter() if fmt in {"console", "text"} else JsonFormatter()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    handler.addFilter(ConversationIdFilter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())

    _configured = True
