from __future__ import annotations

import asyncio
import json

import pytest

import agents.agent_b.mcp_client as mcp_client
from agents.flow_logging import set_flow_id


class FakeResponse:
    def __init__(self, *, status_code: int = 200, headers: dict[str, str] | None = None, json_data: dict | None = None, text: str | None = None):
        self.status_code = status_code
        self.headers = headers or {}
        self._json_data = json_data or {}
        self.text = text if text is not None else json.dumps(self._json_data)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}: {self.text}")

    def json(self):
        return self._json_data


class FakeAsyncClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, *, json=None, headers=None):
        self.calls.append({"url": url, "json": json, "headers": dict(headers or {})})
        if not self.responses:
            raise AssertionError(f"No mocked response left for {json.get('method') if isinstance(json, dict) else json!r}")
        return self.responses.pop(0)


def _sse_body(payload: dict[str, object]) -> str:
    return f"data: {json.dumps(payload)}\n\n"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (json.dumps({"jsonrpc": "2.0", "result": {"ok": True}}), {"jsonrpc": "2.0", "result": {"ok": True}}),
        (_sse_body({"jsonrpc": "2.0", "result": {"ok": True}}), {"jsonrpc": "2.0", "result": {"ok": True}}),
    ],
)
def test_agent_b_mcp_client_parses_plain_json_and_sse_payloads(raw, expected):
    assert mcp_client._parse_mcp_payload(raw) == expected


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("data: [DONE]\n\n", "MCP response payload is empty"),
        ("   ", "MCP response payload is empty"),
        ("not-json", "MCP response payload is malformed"),
        (json.dumps(["not", "an", "object"]), "MCP response payload must be a JSON object"),
    ],
)
def test_agent_b_mcp_client_rejects_bad_mcp_payloads(raw, message):
    with pytest.raises(ValueError, match=message):
        mcp_client._parse_mcp_payload(raw)


def test_agent_b_mcp_client_uses_proven_request_sequence_and_session_reuse(monkeypatch, tmp_path):
    async def _run():
        token_path = tmp_path / "token-c.txt"
        token_path.write_text("token-c\n", encoding="utf-8")
        monkeypatch.setenv("TOKEN_C_FILE", str(token_path))
        set_flow_id("flow-42")

        responses = [
            FakeResponse(
                headers={"Mcp-Session-Id": "sess-abc"},
                text=_sse_body({"jsonrpc": "2.0", "result": {"protocolVersion": "2025-03-26", "capabilities": {}, "serverInfo": {"name": "banking-mcp", "version": "1.0.0"}}}),
            ),
            FakeResponse(status_code=202, text=""),
            FakeResponse(
                text=_sse_body({"jsonrpc": "2.0", "result": {"tools": [{"name": "get_account_summary", "description": "Read a balance"}]}}),
            ),
            FakeResponse(
                text=_sse_body({"jsonrpc": "2.0", "result": {"content": [{"type": "text", "text": "Balance for acct-1001 is 12345.67"}]}}),
            ),
        ]
        fake_client = FakeAsyncClient(responses)
        monkeypatch.setattr(mcp_client.httpx, "AsyncClient", lambda *args, **kwargs: fake_client)
        recorded = []
        monkeypatch.setattr(mcp_client, "log_flow_event", lambda *args, **kwargs: recorded.append({"args": args, "kwargs": dict(kwargs)}))

        result = await mcp_client.get_account_summary("acct-1001")

        assert result == "Balance for acct-1001 is 12345.67"
        assert [call["json"]["method"] for call in fake_client.calls] == [
            "initialize",
            "notifications/initialized",
            "tools/list",
            "tools/call",
        ]
        assert fake_client.calls[0]["headers"]["Authorization"] == "Bearer token-c"
        assert fake_client.calls[0]["headers"]["Accept"] == "application/json, text/event-stream"
        assert fake_client.calls[0]["headers"]["MCP-Protocol-Version"] == "2025-03-26"
        assert fake_client.calls[0]["headers"]["X-Flow-ID"] == "flow-42"
        for call in fake_client.calls[1:]:
            assert call["headers"]["Mcp-Session-Id"] == "sess-abc"
            assert call["headers"]["X-Flow-ID"] == "flow-42"
        assert all("token-c" not in json.dumps(recorded).lower() for _ in [0])
        assert all("acct-1001" not in json.dumps(recorded).lower() for _ in [0])

    asyncio.run(_run())


def test_agent_b_mcp_client_requires_get_account_summary_and_rejects_create_transfer(monkeypatch, tmp_path):
    async def _run():
        token_path = tmp_path / "token-c.txt"
        token_path.write_text("token-c\n", encoding="utf-8")
        monkeypatch.setenv("TOKEN_C_FILE", str(token_path))
        set_flow_id("flow-43")

        responses = [
            FakeResponse(headers={"Mcp-Session-Id": "sess-xyz"}, text=_sse_body({"jsonrpc": "2.0", "result": {"protocolVersion": "2025-03-26"}})),
            FakeResponse(status_code=202, text=""),
            FakeResponse(text=_sse_body({"jsonrpc": "2.0", "result": {"tools": [{"name": "create_transfer"}, {"name": "get_account_summary"}]}})),
        ]
        fake_client = FakeAsyncClient(responses)
        monkeypatch.setattr(mcp_client.httpx, "AsyncClient", lambda *args, **kwargs: fake_client)

        with pytest.raises(ValueError, match="create_transfer|get_account_summary"):
            await mcp_client.get_account_summary("acct-1001")

    asyncio.run(_run())


def test_agent_b_mcp_client_fails_closed_on_initialize_error_even_with_session_header(monkeypatch, tmp_path):
    async def _run():
        token_path = tmp_path / "token-c.txt"
        token_path.write_text("token-c\n", encoding="utf-8")
        monkeypatch.setenv("TOKEN_C_FILE", str(token_path))
        set_flow_id("flow-48")

        responses = [
            FakeResponse(
                headers={"Mcp-Session-Id": "sess-error"},
                text=_sse_body({"jsonrpc": "2.0", "error": {"code": -32603, "message": "hidden"}}),
            ),
        ]
        fake_client = FakeAsyncClient(responses)
        monkeypatch.setattr(mcp_client.httpx, "AsyncClient", lambda *args, **kwargs: fake_client)

        with pytest.raises(ValueError, match="MCP initialize failed"):
            await mcp_client.get_account_summary("acct-1001")

    asyncio.run(_run())


def test_agent_b_mcp_client_fails_closed_when_initialize_result_is_not_an_object(monkeypatch, tmp_path):
    async def _run():
        token_path = tmp_path / "token-c.txt"
        token_path.write_text("token-c\n", encoding="utf-8")
        monkeypatch.setenv("TOKEN_C_FILE", str(token_path))
        set_flow_id("flow-49")

        responses = [
            FakeResponse(
                headers={"Mcp-Session-Id": "sess-result"},
                text=_sse_body({"jsonrpc": "2.0", "result": ["not", "an", "object"]}),
            ),
        ]
        fake_client = FakeAsyncClient(responses)
        monkeypatch.setattr(mcp_client.httpx, "AsyncClient", lambda *args, **kwargs: fake_client)

        with pytest.raises(ValueError, match="MCP initialize response is invalid"):
            await mcp_client.get_account_summary("acct-1001")

    asyncio.run(_run())


def test_agent_b_mcp_client_fails_closed_when_tools_list_missing_tools_list(monkeypatch, tmp_path):
    async def _run():
        token_path = tmp_path / "token-c.txt"
        token_path.write_text("token-c\n", encoding="utf-8")
        monkeypatch.setenv("TOKEN_C_FILE", str(token_path))
        set_flow_id("flow-50")

        responses = [
            FakeResponse(headers={"Mcp-Session-Id": "sess-tools"}, text=_sse_body({"jsonrpc": "2.0", "result": {"protocolVersion": "2025-03-26"}})),
            FakeResponse(status_code=202, text=""),
            FakeResponse(text=_sse_body({"jsonrpc": "2.0", "result": {"tools": {"name": "get_account_summary"}}})),
        ]
        fake_client = FakeAsyncClient(responses)
        monkeypatch.setattr(mcp_client.httpx, "AsyncClient", lambda *args, **kwargs: fake_client)

        with pytest.raises(ValueError, match="MCP tools/list response is invalid"):
            await mcp_client.get_account_summary("acct-1001")

    asyncio.run(_run())


def test_agent_b_mcp_client_fails_closed_when_token_missing(monkeypatch):
    async def _run():
        monkeypatch.delenv("TOKEN_C_FILE", raising=False)
        set_flow_id("flow-44")
        with pytest.raises(RuntimeError, match="TOKEN_C_FILE"):
            await mcp_client.get_account_summary("acct-1001")

    asyncio.run(_run())


def test_agent_b_mcp_client_fails_closed_when_session_id_missing(monkeypatch, tmp_path):
    async def _run():
        token_path = tmp_path / "token-c.txt"
        token_path.write_text("token-c\n", encoding="utf-8")
        monkeypatch.setenv("TOKEN_C_FILE", str(token_path))
        set_flow_id("flow-45")

        responses = [
            FakeResponse(text=_sse_body({"jsonrpc": "2.0", "result": {"protocolVersion": "2025-03-26"}})),
        ]
        fake_client = FakeAsyncClient(responses)
        monkeypatch.setattr(mcp_client.httpx, "AsyncClient", lambda *args, **kwargs: fake_client)

        with pytest.raises(RuntimeError, match="session id"):
            await mcp_client.get_account_summary("acct-1001")

    asyncio.run(_run())


def test_agent_b_mcp_client_fails_closed_for_malformed_or_failed_mcp_responses(monkeypatch, tmp_path):
    async def _run():
        token_path = tmp_path / "token-c.txt"
        token_path.write_text("token-c\n", encoding="utf-8")
        monkeypatch.setenv("TOKEN_C_FILE", str(token_path))
        set_flow_id("flow-46")

        responses = [
            FakeResponse(headers={"Mcp-Session-Id": "sess-456"}, text=_sse_body({"jsonrpc": "2.0", "result": {"protocolVersion": "2025-03-26"}})),
            FakeResponse(status_code=202, text=""),
            FakeResponse(text=_sse_body({"jsonrpc": "2.0", "error": {"code": -32603, "message": "tool list is broken"}})),
        ]
        fake_client = FakeAsyncClient(responses)
        monkeypatch.setattr(mcp_client.httpx, "AsyncClient", lambda *args, **kwargs: fake_client)
        emitted = []
        monkeypatch.setattr(mcp_client, "log_flow_event", lambda *args, **kwargs: emitted.append(str(kwargs)))

        with pytest.raises(ValueError, match="tools/list|tool list|MCP"):
            await mcp_client.get_account_summary("acct-1001")

        payload = "\n".join(emitted)
        assert "token-c" not in payload.lower()
        assert "acct-1001" not in payload.lower()

    asyncio.run(_run())


def test_agent_b_mcp_client_does_not_log_tokens_or_account_data(monkeypatch, tmp_path):
    async def _run():
        token_path = tmp_path / "token-c.txt"
        token_path.write_text("token-c\n", encoding="utf-8")
        monkeypatch.setenv("TOKEN_C_FILE", str(token_path))
        set_flow_id("flow-47")

        responses = [
            FakeResponse(headers={"Mcp-Session-Id": "sess-999"}, text=_sse_body({"jsonrpc": "2.0", "result": {"protocolVersion": "2025-03-26"}})),
            FakeResponse(status_code=202, text=""),
            FakeResponse(text=_sse_body({"jsonrpc": "2.0", "result": {"tools": [{"name": "get_account_summary"}]}})),
            FakeResponse(text=_sse_body({"jsonrpc": "2.0", "result": {"content": [{"type": "text", "text": "Balance for acct-1001 is 12345.67"}]}})),
        ]
        fake_client = FakeAsyncClient(responses)
        monkeypatch.setattr(mcp_client.httpx, "AsyncClient", lambda *args, **kwargs: fake_client)
        emitted = []
        monkeypatch.setattr(mcp_client, "log_flow_event", lambda *args, **kwargs: emitted.append(str(kwargs)))

        result = await mcp_client.get_account_summary("acct-1001")

        assert result == "Balance for acct-1001 is 12345.67"
        payload = "\n".join(emitted)
        assert "token-c" not in payload.lower()
        assert "acct-1001" not in payload.lower()
        assert "flow-47" in payload

    asyncio.run(_run())
