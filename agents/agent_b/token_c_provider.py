from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Any

import msal

from agents.flow_logging import extract_raw_user_identity, get_flow_id, log_flow_event
from agents.token_provider import FileTokenProvider

from .delegated_token_context import get_delegated_token_b

TOKEN_C_MODE_FILE = "file"
TOKEN_C_MODE_OBO = "obo"
TOKEN_C_MODE_ENV = "AGENT_B_TOKEN_C_MODE"
AGENT_B_TOKEN_C_MODE = TOKEN_C_MODE_ENV


def _parse_banking_scopes(value: str) -> tuple[str, ...]:
    scopes = tuple(dict.fromkeys(part for chunk in value.split(",") for part in chunk.split() if part))
    if not scopes:
        raise TokenCResolutionError("Token C OBO configuration is incomplete", category="missing_configuration")
    return scopes


class TokenCResolutionError(RuntimeError):
    def __init__(self, message: str, *, category: str):
        super().__init__(message)
        self.category = category


def derive_banking_default_scope(scopes: tuple[str, ...] | list[str]) -> str:
    """Return the single `<resource>/.default` OBO scope for fully qualified delegated Banking scopes."""
    invalid = TokenCResolutionError("Token C OBO configuration is invalid", category="invalid_configuration")
    resources: set[str] = set()
    for scope in scopes:
        resource, separator, name = str(scope).rpartition("/")
        scheme, scheme_separator, remainder = resource.partition("://")
        if (
            not separator
            or not scheme_separator
            or not scheme
            or not remainder
            or not name
            or name == ".default"
            or any(char.isspace() for char in scope)
        ):
            raise invalid
        resources.add(resource)
    if len(resources) != 1:
        raise invalid
    return f"{resources.pop()}/.default"


def _normalize_mode(value: str | None) -> str:
    mode = (value or TOKEN_C_MODE_FILE).strip().lower()
    if not mode:
        return TOKEN_C_MODE_FILE
    if mode not in {TOKEN_C_MODE_FILE, TOKEN_C_MODE_OBO}:
        raise TokenCResolutionError("Token C mode is unsupported", category="unsupported_mode")
    return mode


def _read_nonempty_file(path: str, *, failure_category: str, failure_message: str) -> str:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:  # pragma: no cover - narrow failure path
        raise TokenCResolutionError(failure_message, category=failure_category) from exc
    value = text.strip()
    if not value:
        raise TokenCResolutionError(failure_message, category=failure_category)
    return value


@dataclass(frozen=True)
class AgentBOboTokenCProvider:
    tenant_id: str
    client_id: str
    client_secret_file: str
    banking_scopes: tuple[str, ...]
    msal_client_factory: Callable[..., Any] = msal.ConfidentialClientApplication

    @classmethod
    def from_env(
        cls,
        *,
        msal_client_factory: Callable[..., Any] | None = None,
    ) -> "AgentBOboTokenCProvider":
        if msal_client_factory is None:
            msal_client_factory = msal.ConfidentialClientApplication
        tenant_id = os.getenv("ENTRA_TENANT_ID", "").strip()
        client_id = os.getenv("ENTRA_AGENT_B_CLIENT_ID", "").strip()
        client_secret_file = os.getenv("ENTRA_AGENT_B_CLIENT_SECRET_FILE", "").strip()
        banking_scope_value = (
            os.getenv("ENTRA_BANKING_SCOPES", "").strip()
            or os.getenv("ENTRA_BANKING_SCOPE", "").strip()
        )
        missing = [name for name, value in (
            ("ENTRA_TENANT_ID", tenant_id),
            ("ENTRA_AGENT_B_CLIENT_ID", client_id),
            ("ENTRA_AGENT_B_CLIENT_SECRET_FILE", client_secret_file),
            ("ENTRA_BANKING_SCOPES or ENTRA_BANKING_SCOPE", banking_scope_value),
        ) if not value]
        if missing:
            raise TokenCResolutionError("Token C OBO configuration is incomplete", category="missing_configuration")
        banking_scopes = _parse_banking_scopes(banking_scope_value)
        derive_banking_default_scope(banking_scopes)
        return cls(
            tenant_id=tenant_id,
            client_id=client_id,
            client_secret_file=client_secret_file,
            banking_scopes=banking_scopes,
            msal_client_factory=msal_client_factory,
        )

    def _read_client_secret(self) -> str:
        return _read_nonempty_file(
            self.client_secret_file,
            failure_category="missing_client_secret",
            failure_message="Token C OBO failed: Agent B client secret file is missing, unreadable, or empty",
        )

    def acquire_token(self, user_assertion: str) -> str:
        if not isinstance(user_assertion, str) or not user_assertion.strip():
            raise TokenCResolutionError("Token C OBO failed: missing request-scoped Token B", category="missing_token_b")

        default_scope = derive_banking_default_scope(self.banking_scopes)
        client_secret = self._read_client_secret()
        authority = f"https://login.microsoftonline.com/{self.tenant_id}"
        try:
            obo_app = self.msal_client_factory(
                client_id=self.client_id,
                client_credential=client_secret,
                authority=authority,
            )
            obo_result = obo_app.acquire_token_on_behalf_of(
                user_assertion=user_assertion,
                scopes=[default_scope],
            )
        except TokenCResolutionError:
            raise
        except Exception as exc:  # pragma: no cover - defensive wrapper
            raise TokenCResolutionError("Token C OBO failed: MSAL exchange failed", category="msal_exchange_failed") from exc

        if not isinstance(obo_result, dict):
            raise TokenCResolutionError("Token C OBO failed: MSAL response was invalid", category="msal_response_invalid")
        access_token = obo_result.get("access_token")
        if not isinstance(access_token, str) or not access_token.strip():
            raise TokenCResolutionError("Token C OBO failed: access token missing", category="missing_access_token")

        identity_fields = {}
        if os.getenv("POC_LOG_RAW_USER_ID") == "true":
            identity_fields = extract_raw_user_identity(token=user_assertion)
        log_flow_event(
            "token_c_obo_completed",
            component="agent_b.token_c_provider",
            flow_id=get_flow_id(),
            http_path="/mcp",
            http_status=200,
            elapsed_ms=0,
            success=True,
            **identity_fields,
        )
        return access_token.strip()


async def resolve_agent_b_token_c() -> str:
    try:
        mode = _normalize_mode(os.getenv(TOKEN_C_MODE_ENV))
        if mode == TOKEN_C_MODE_FILE:
            return FileTokenProvider.from_env("TOKEN_C_FILE").token

        provider = AgentBOboTokenCProvider.from_env()
        token_b = get_delegated_token_b()
        if not token_b:
            raise TokenCResolutionError("Token C OBO failed: missing request-scoped Token B", category="missing_token_b")
        return await asyncio.to_thread(provider.acquire_token, token_b)
    except TokenCResolutionError as exc:
        log_flow_event(
            "token_c_obo_failed",
            component="agent_b.token_c_provider",
            flow_id=get_flow_id(),
            http_path="/mcp",
            http_status=200,
            elapsed_ms=0,
            success=False,
        )
        raise


__all__ = [
    "AGENT_B_TOKEN_C_MODE",
    "AgentBOboTokenCProvider",
    "TOKEN_C_MODE_ENV",
    "TOKEN_C_MODE_FILE",
    "TOKEN_C_MODE_OBO",
    "TokenCResolutionError",
    "derive_banking_default_scope",
    "resolve_agent_b_token_c",
]
