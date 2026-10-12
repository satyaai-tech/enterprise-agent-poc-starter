from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from contextvars import ContextVar
from typing import Any

LOGGER_NAME = "phase4.flow"
FLOW_CONTEXT: ContextVar[str | None] = ContextVar("phase4_flow_id", default=None)


def configure_flow_logging() -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(os.getenv("FLOW_LOG_LEVEL", "INFO").upper())
    logger.propagate = False
    if not logger.handlers:
        handler = logging.StreamHandler(stream=sys.stderr)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    return logger


def get_flow_id() -> str:
    flow_id = FLOW_CONTEXT.get()
    if flow_id:
        return flow_id
    flow_id = uuid.uuid4().hex[:12]
    FLOW_CONTEXT.set(flow_id)
    return flow_id


def set_flow_id(flow_id: str | None) -> Any:
    return FLOW_CONTEXT.set(flow_id)


def reset_flow_id(token: Any) -> None:
    FLOW_CONTEXT.reset(token)


def log_flow_event(
    event_name: str,
    component: str,
    *,
    flow_id: str | None = None,
    http_path: str | None = None,
    http_status: int | None = None,
    elapsed_ms: int | None = None,
    success: bool = True,
) -> None:
    logger = configure_flow_logging()
    log_record = {
        "event": event_name,
        "flow_id": flow_id or get_flow_id(),
        "component": component,
        "http_path": http_path,
        "http_status": http_status,
        "elapsed_ms": elapsed_ms,
        "success": bool(success),
    }
    logger.info(json.dumps(log_record, separators=(",", ":")))
