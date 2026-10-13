from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from contextvars import ContextVar
from typing import Any

import jwt

LOGGER_NAME = "phase4.flow"
FLOW_CONTEXT: ContextVar[str | None] = ContextVar("phase4_flow_id", default=None)


def is_poc_raw_user_id_enabled() -> bool:
    return os.getenv("POC_LOG_RAW_USER_ID") == "true"


def extract_raw_user_identity(*, token: str | None = None, claims: dict[str, Any] | None = None) -> dict[str, str]:
    if claims is None:
        if not isinstance(token, str) or not token.strip():
            return {}
        try:
            claims = jwt.decode(
                token,
                options={
                    "verify_signature": False,
                    "verify_exp": False,
                    "verify_nbf": False,
                    "verify_aud": False,
                    "verify_iss": False,
                },
            )
        except Exception:
            return {}
    if not isinstance(claims, dict):
        return {}

    oid = claims.get("oid")
    tid = claims.get("tid")
    preferred_username = claims.get("preferred_username")
    if isinstance(oid, str):
        oid = oid.strip()
    else:
        oid = None
    if isinstance(tid, str):
        tid = tid.strip()
    else:
        tid = None
    if isinstance(preferred_username, str):
        preferred_username = preferred_username.strip()
    else:
        preferred_username = None
    if not oid and isinstance(claims.get("sub"), str):
        oid = claims["sub"].strip() or None
    if oid is None and tid is None:
        return {}
    result: dict[str, str] = {}
    if oid:
        result["oid"] = oid
    if tid:
        result["tid"] = tid
    if preferred_username:
        result["preferred_username"] = preferred_username
    return result


def log_raw_user_identity(
    event_name: str,
    component: str,
    *,
    flow_id: str | None = None,
    token: str | None = None,
    claims: dict[str, Any] | None = None,
    http_path: str | None = None,
    http_status: int | None = None,
    elapsed_ms: int | None = None,
    success: bool = True,
    **extra_fields: Any,
) -> None:
    if not is_poc_raw_user_id_enabled():
        return None
    fields = extract_raw_user_identity(token=token, claims=claims)
    if not fields:
        return None
    return log_flow_event(
        event_name,
        component,
        flow_id=flow_id,
        http_path=http_path,
        http_status=http_status,
        elapsed_ms=elapsed_ms,
        success=success,
        **fields,
        **extra_fields,
    )


log_poc_user_identity = log_raw_user_identity
maybe_log_raw_user_identity = log_raw_user_identity


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
    **extra_fields: Any,
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
    if extra_fields:
        log_record.update(extra_fields)
    logger.info(json.dumps(log_record, separators=(",", ":")))


__all__ = [
    "FLOW_CONTEXT",
    "LOGGER_NAME",
    "configure_flow_logging",
    "extract_raw_user_identity",
    "get_flow_id",
    "is_poc_raw_user_id_enabled",
    "log_flow_event",
    "log_poc_user_identity",
    "log_raw_user_identity",
    "maybe_log_raw_user_identity",
    "reset_flow_id",
    "set_flow_id",
]
