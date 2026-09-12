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
        extra = {
            k: v
            for k, v in record.__dict__.items()
            if k not in _RESERVED_RECORD_KEYS and k not in payload
        }
        payload.update(extra)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


_configured = False


def setup_logging() -> None:
    """Configura el root logger una sola vez. Idempotente — llamar libremente."""
    global _configured
    if _configured:
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(ConversationIdFilter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())

    _configured = True
