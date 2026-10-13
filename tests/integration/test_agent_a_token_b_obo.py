from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from agents.agent_a.delegated_token_context import get_delegated_token_a
from agents.agent_a.http_app import _wrap_with_flow_id_middleware
from agents.agent_a.token_b_provider import AgentAOboTokenBProvider, TokenBResolutionError, resolve_agent_a_token_b


class FakeConfidentialClient:
    def __init__(self, *, client_id: str, client_credential: str, authority: str):
        assert client_id == "agent-a-client"
        assert client_credential == "agent-a-secret"
        assert authority.endswith("/tenant-live")

    def acquire_token_on_behalf_of(self, *, user_assertion: str, scopes: list[str]):
        assert user_assertion == "token-a"
        assert scopes == ["api://agent-b/AgentB.Access"]
        return {"access_token": "token-b"}


def _set_obo_env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    secret = tmp_path / "agent-a-secret"
    secret.write_text("agent-a-secret\n", encoding="utf-8")
    monkeypatch.setenv("AGENT_A_TOKEN_B_MODE", "obo")
    monkeypatch.setenv("ENTRA_TENANT_ID", "tenant-live")
    monkeypatch.setenv("ENTRA_AGENT_A_CLIENT_ID", "agent-a-client")
    monkeypatch.setenv("ENTRA_AGENT_A_CLIENT_SECRET_FILE", str(secret))
    monkeypatch.setenv("ENTRA_AGENT_B_SCOPE", "api://agent-b/AgentB.Access")


def test_agent_a_obo_provider_exchanges_token_a_for_token_b(monkeypatch, tmp_path) -> None:
    _set_obo_env(monkeypatch, tmp_path)
    provider = AgentAOboTokenBProvider.from_env(msal_client_factory=FakeConfidentialClient)
    assert provider.acquire_token("token-a") == "token-b"


def test_agent_a_obo_fails_closed_without_request_token(monkeypatch, tmp_path) -> None:
    _set_obo_env(monkeypatch, tmp_path)
    with pytest.raises(TokenBResolutionError, match="missing request-scoped Token A"):
        asyncio.run(resolve_agent_a_token_b())


def test_agent_a_http_boundary_captures_and_resets_token_a() -> None:
    app = FastAPI()

    @app.get("/context")
    def context() -> dict[str, bool]:
        return {"token_a_present": get_delegated_token_a() is not None}

    wrapped = _wrap_with_flow_id_middleware(app)
    response = TestClient(wrapped).get("/context", headers={"Authorization": "Bearer token-a"})
    assert response.status_code == 200
    assert response.json() == {"token_a_present": True}
    assert get_delegated_token_a() is None
