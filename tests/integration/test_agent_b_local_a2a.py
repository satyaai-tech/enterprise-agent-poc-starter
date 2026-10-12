from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.agent_b.a2a_server import A2A_AGENT_CARD_URL, A2A_HOST, A2A_PORT, create_a2a_app
from agents.agent_b.a2a_smoke import main


def test_create_a2a_app_uses_local_host_and_port(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3:8b")
    monkeypatch.setenv("OLLAMA_API_BASE", "http://localhost:11434")

    import agents.agent_b.a2a_server as a2a_server_module

    monkeypatch.setattr(a2a_server_module, "A2A_PUBLIC_URL", None)

    mock_agent = MagicMock()
    with patch("agents.agent_b.a2a_server.build_agent_b", return_value=mock_agent) as build_mock, patch(
        "agents.agent_b.a2a_server.to_a2a", return_value="a2a-app"
    ) as to_a2a_mock:
        app = create_a2a_app()

    assert app == "a2a-app"
    build_mock.assert_called_once_with()
    to_a2a_mock.assert_called_once_with(
        mock_agent,
        host="127.0.0.1",
        port=8001,
        protocol="http",
    )


def test_a2a_agent_card_url_and_local_binding():
    assert A2A_HOST == "127.0.0.1"
    assert A2A_PORT == 8001
    assert A2A_AGENT_CARD_URL == "http://127.0.0.1:8001/.well-known/agent-card.json"


def test_guarded_local_a2a_smoke_requires_flag(capsys):
    exit_code = main([])
    out = capsys.readouterr().out.strip()
    assert exit_code == 2
    assert out == "FAIL"


def test_guarded_local_a2a_smoke_handles_response_payload(monkeypatch):
    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self):
            self.calls = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url):
            self.calls.append(("get", url))
            return FakeResponse({"name": "agent-b-local-test"})

        async def post(self, url, json):
            self.calls.append(("post", url, json))
            return FakeResponse({"result": {"message": {"parts": [{"text": "PASS"}]}}})

    client = FakeClient()
    monkeypatch.setattr("agents.agent_b.a2a_smoke.httpx.AsyncClient", lambda *args, **kwargs: client)
    assert main(["--live-local-a2a"]) == 0
