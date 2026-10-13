from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from a2a.utils.constants import TransportProtocol

from agents.agent_a.a2a_client import fetch_agent_b_agent_card, send_agent_b_message
from agents.agent_a.a2a_smoke import _run_live_probe, main


def test_main_requires_live_flag() -> None:
    assert main([]) == 2


def test_fetch_agent_b_agent_card_uses_resolver() -> None:
    async def fake_get_agent_card(self):
        return SimpleNamespace(name="agent-b", description="banking")

    original = __import__("agents.agent_a.a2a_client", fromlist=["A2ACardResolver"]).A2ACardResolver.get_agent_card
    __import__("agents.agent_a.a2a_client", fromlist=["A2ACardResolver"]).A2ACardResolver.get_agent_card = fake_get_agent_card
    try:
        card = asyncio.run(fetch_agent_b_agent_card("http://127.0.0.1:8001"))
        assert card.name == "agent-b"
        assert card.description == "banking"
    finally:
        __import__("agents.agent_a.a2a_client", fromlist=["A2ACardResolver"]).A2ACardResolver.get_agent_card = original


def test_send_agent_b_message_extracts_a2a_text(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    token_path = tmp_path / "token-b.txt"
    token_path.write_text("token-b\n", encoding="utf-8")
    monkeypatch.setenv("TOKEN_B_FILE", str(token_path))

    class DummyClient:
        async def send_message(self, request):
            yield SimpleNamespace(
                message=SimpleNamespace(
                    parts=[SimpleNamespace(text="PASS")],
                )
            )

        async def close(self):
            return None

    async def fake_create_client(base_url, **kwargs):
        client_config = kwargs.get("client_config")
        assert client_config is not None
        assert client_config.supported_protocol_bindings == [
            TransportProtocol.JSONRPC,
            TransportProtocol.HTTP_JSON,
        ]
        return DummyClient()

    async def fake_fetch_agent_b_agent_card(base_url):
        return SimpleNamespace(name="agent-b")

    import agents.agent_a.a2a_client as a2a_client_module

    monkeypatch.setattr(a2a_client_module, "fetch_agent_b_agent_card", fake_fetch_agent_b_agent_card)
    monkeypatch.setattr(a2a_client_module, "create_client", fake_create_client)

    result = asyncio.run(send_agent_b_message("delegate now", base_url="http://127.0.0.1:8001"))
    assert result == "PASS"


def test_run_live_probe_uses_agent_a_then_agent_b() -> None:
    class DummyRunner:
        def __init__(self, agent):
            self.agent = agent
            self.session_service = SimpleNamespace(
                create_session=self._create_session
            )

        async def _create_session(self, **kwargs):
            return None

        async def run_async(self, **kwargs):
            import agents.agent_a.agent as agent_module

            await agent_module.delegate_to_agent_b("delegate to agent b")
            yield SimpleNamespace(
                is_final_response=lambda: True,
                content=SimpleNamespace(
                    parts=[SimpleNamespace(text="PASS", thought=False)]
                ),
            )

    import agents.agent_a.a2a_smoke as a2a_smoke_module
    import agents.agent_a.agent as agent_module
    import agents.agent_a.a2a_client as a2a_client_module

    original_build_agent_a = a2a_smoke_module.build_agent_a
    original_runner = a2a_smoke_module.InMemoryRunner
    original_send = a2a_client_module.send_agent_b_message
    original_agent_send = agent_module.send_agent_b_message

    agent_module.reset_delegation_tool_invocation_count()
    a2a_client_module.reset_a2a_client_invocation_count()

    async def fake_send_agent_b_message(message):
        a2a_client_module.A2A_CLIENT_INVOCATION_COUNT += 1
        return "PASS"

    agent_module.send_agent_b_message = fake_send_agent_b_message
    a2a_client_module.send_agent_b_message = fake_send_agent_b_message
    a2a_smoke_module.build_agent_a = lambda: object()
    a2a_smoke_module.InMemoryRunner = DummyRunner
    try:
        result = asyncio.run(_run_live_probe())
        assert result == "PASS"
        assert agent_module.get_delegation_tool_invocation_count() == 1
        assert a2a_client_module.get_a2a_client_invocation_count() == 1
    finally:
        a2a_smoke_module.build_agent_a = original_build_agent_a
        a2a_smoke_module.InMemoryRunner = original_runner
        a2a_client_module.send_agent_b_message = original_send
        agent_module.send_agent_b_message = original_agent_send


def test_run_live_probe_rejects_pass_without_tool_invocation() -> None:
    class DummyRunner:
        def __init__(self, agent):
            self.agent = agent
            self.session_service = SimpleNamespace(
                create_session=self._create_session
            )

        async def _create_session(self, **kwargs):
            return None

        async def run_async(self, **kwargs):
            yield SimpleNamespace(
                is_final_response=lambda: True,
                content=SimpleNamespace(
                    parts=[SimpleNamespace(text="PASS", thought=False)]
                ),
            )

    import agents.agent_a.a2a_smoke as a2a_smoke_module
    import agents.agent_a.agent as agent_module
    import agents.agent_a.a2a_client as a2a_client_module

    original_build_agent_a = a2a_smoke_module.build_agent_a
    original_runner = a2a_smoke_module.InMemoryRunner
    agent_module.reset_delegation_tool_invocation_count()
    a2a_client_module.reset_a2a_client_invocation_count()
    a2a_smoke_module.build_agent_a = lambda: object()
    a2a_smoke_module.InMemoryRunner = DummyRunner
    try:
        with pytest.raises(ValueError, match="delegate_to_agent_b|A2A client|returned the delegated PASS result"):
            asyncio.run(_run_live_probe())
    finally:
        a2a_smoke_module.build_agent_a = original_build_agent_a
        a2a_smoke_module.InMemoryRunner = original_runner
