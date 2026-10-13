from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import msal

from agents.flow_logging import extract_raw_user_identity, get_flow_id, log_flow_event
from agents.token_provider import FileTokenProvider

from .delegated_token_context import get_delegated_token_a

TOKEN_B_MODE_FILE = "file"
TOKEN_B_MODE_OBO = "obo"
TOKEN_B_MODE_ENV = "AGENT_A_TOKEN_B_MODE"


class TokenBResolutionError(RuntimeError):
    def __init__(self, message: str, *, category: str):
        super().__init__(message)
        self.category = category


def _normalize_mode(value: str | None) -> str:
    mode = (value or TOKEN_B_MODE_FILE).strip().lower() or TOKEN_B_MODE_FILE
    if mode not in {TOKEN_B_MODE_FILE, TOKEN_B_MODE_OBO}:
        raise TokenBResolutionError("Token B mode is unsupported", category="unsupported_mode")
    return mode


def _read_nonempty_file(path: str) -> str:
    try:
        value = Path(path).read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise TokenBResolutionError(
            "Token B OBO failed: Agent A client secret file is missing, unreadable, or empty",
            category="missing_client_secret",
        ) from exc
    if not value:
        raise TokenBResolutionError(
            "Token B OBO failed: Agent A client secret file is missing, unreadable, or empty",
            category="missing_client_secret",
        )
    return value


@dataclass(frozen=True)
class AgentAOboTokenBProvider:
    tenant_id: str
    client_id: str
    client_secret_file: str
    agent_b_scope: str
    msal_client_factory: Callable[..., Any] = msal.ConfidentialClientApplication

    @classmethod
    def from_env(cls, *, msal_client_factory: Callable[..., Any] | None = None) -> "AgentAOboTokenBProvider":
        values = {
            "tenant_id": os.getenv("ENTRA_TENANT_ID", "").strip(),
            "client_id": os.getenv("ENTRA_AGENT_A_CLIENT_ID", "").strip(),
            "client_secret_file": os.getenv("ENTRA_AGENT_A_CLIENT_SECRET_FILE", "").strip(),
            "agent_b_scope": os.getenv("ENTRA_AGENT_B_SCOPE", "").strip(),
        }
        if any(not value for value in values.values()):
            raise TokenBResolutionError("Token B OBO configuration is incomplete", category="missing_configuration")
        return cls(**values, msal_client_factory=msal_client_factory or msal.ConfidentialClientApplication)

    def acquire_token(self, user_assertion: str) -> str:
        if not isinstance(user_assertion, str) or not user_assertion.strip():
            raise TokenBResolutionError("Token B OBO failed: missing request-scoped Token A", category="missing_token_a")
        try:
            app = self.msal_client_factory(
                client_id=self.client_id,
                client_credential=_read_nonempty_file(self.client_secret_file),
                authority=f"https://login.microsoftonline.com/{self.tenant_id}",
            )
            result = app.acquire_token_on_behalf_of(user_assertion=user_assertion, scopes=[self.agent_b_scope])
        except TokenBResolutionError:
            raise
        except Exception as exc:
            raise TokenBResolutionError("Token B OBO failed: MSAL exchange failed", category="msal_exchange_failed") from exc
        token = result.get("access_token") if isinstance(result, dict) else None
        if not isinstance(token, str) or not token.strip():
            raise TokenBResolutionError("Token B OBO failed: access token missing", category="missing_access_token")
        identity = extract_raw_user_identity(token=user_assertion) if os.getenv("POC_LOG_RAW_USER_ID") == "true" else {}
        log_flow_event(
            "token_b_obo_completed",
            component="agent_a.token_b_provider",
            flow_id=get_flow_id(),
            http_path="a2a:send_message",
            http_status=200,
            elapsed_ms=0,
            success=True,
            **identity,
        )
        return token.strip()


async def resolve_agent_a_token_b() -> str:
    try:
        if _normalize_mode(os.getenv(TOKEN_B_MODE_ENV)) == TOKEN_B_MODE_FILE:
            return FileTokenProvider.from_env("TOKEN_B_FILE").token
        token_a = get_delegated_token_a()
        if not token_a:
            raise TokenBResolutionError("Token B OBO failed: missing request-scoped Token A", category="missing_token_a")
        return await asyncio.to_thread(AgentAOboTokenBProvider.from_env().acquire_token, token_a)
    except TokenBResolutionError:
        log_flow_event(
            "token_b_obo_failed",
            component="agent_a.token_b_provider",
            flow_id=get_flow_id(),
            http_path="a2a:send_message",
            http_status=200,
            elapsed_ms=0,
            success=False,
        )
        raise


__all__ = [
    "AgentAOboTokenBProvider",
    "TOKEN_B_MODE_ENV",
    "TOKEN_B_MODE_FILE",
    "TOKEN_B_MODE_OBO",
    "TokenBResolutionError",
    "resolve_agent_a_token_b",
]
