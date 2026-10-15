from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

import agents.agent_b.a2a_server as a2a_server
import agents.agent_b.mcp_client as mcp_client
import agents.agent_b.token_c_provider as token_c_provider
from agents.agent_b.delegated_token_context import get_delegated_token_b, reset_delegated_token_b, set_delegated_token_b
from agents.flow_logging import set_flow_id


class FakeResponse:
    def __init__(self, *, status_code: int = 200, headers: dict[str, str] | None = None, text: str = ""):
        self.status_code = status_code
        self.headers = headers or {}
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}: {self.text}")


class FakeAsyncClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, *, json=None, headers=None):
        self.calls.append({"url": url, "json": json, "headers": dict(headers or {})})
        if not self.responses:
            raise AssertionError("No mocked response left")
        return self.responses.pop(0)


def _sse_body(payload: dict[str, object]) -> str:
    return f"data: {json.dumps(payload)}\n\n"


class FakeOboApp:
    def __init__(self, *, client_id: str, client_credential: str, authority: str):
        self.client_id = client_id
        self.client_credential = client_credential
        self.authority = authority
        self.calls: list[dict[str, object]] = []

    def acquire_token_on_behalf_of(self, *, user_assertion: str, scopes: list[str]) -> dict[str, str]:
        self.calls.append({"user_assertion": user_assertion, "scopes": list(scopes)})
        return {"access_token": "token-c-obo"}


def _configure_obo_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    secret_file = tmp_path / "agent-b-client-secret.txt"
    secret_file.write_text("client-secret-value\n", encoding="utf-8")
    monkeypatch.setenv("AGENT_B_TOKEN_C_MODE", "obo")
    monkeypatch.setenv("ENTRA_TENANT_ID", "tenant-123")
    monkeypatch.setenv("ENTRA_AGENT_B_CLIENT_ID", "agent-b-client-id")
    monkeypatch.setenv("ENTRA_AGENT_B_CLIENT_SECRET_FILE", str(secret_file))
    monkeypatch.delenv("ENTRA_BANKING_SCOPES", raising=False)
    monkeypatch.setenv("ENTRA_BANKING_SCOPE", "api://banking/Banking.Read")
    return secret_file


def test_token_c_file_mode_is_default_and_skips_msal(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    token_file = tmp_path / "token-c.txt"
    token_file.write_text("token-c-file-value\n", encoding="utf-8")
    monkeypatch.setenv("TOKEN_C_FILE", str(token_file))
    monkeypatch.delenv("AGENT_B_TOKEN_C_MODE", raising=False)

    called = []
    monkeypatch.setattr(token_c_provider.msal, "ConfidentialClientApplication", lambda *args, **kwargs: called.append((args, kwargs)))

    token = asyncio.run(token_c_provider.resolve_agent_b_token_c())

    assert token == "token-c-file-value"
    assert called == []


def test_token_c_obo_mode_uses_request_scoped_token_b(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _configure_obo_env(monkeypatch, tmp_path)
    set_flow_id("flow-obo-1")
    token_state = set_delegated_token_b("token-b-value")
    events: list[tuple[str, dict[str, object]]] = []

    fake_app = FakeOboApp(client_id="agent-b-client-id", client_credential="client-secret-value", authority="https://login.microsoftonline.com/tenant-123")
    monkeypatch.setattr(token_c_provider.msal, "ConfidentialClientApplication", lambda **kwargs: fake_app)
    monkeypatch.setattr(token_c_provider, "log_flow_event", lambda name, **kwargs: events.append((name, dict(kwargs))))

    try:
        token = asyncio.run(token_c_provider.resolve_agent_b_token_c())
    finally:
        reset_delegated_token_b(token_state)

    assert token == "token-c-obo"
    assert fake_app.client_id == "agent-b-client-id"
    assert fake_app.client_credential == "client-secret-value"
    assert fake_app.authority == "https://login.microsoftonline.com/tenant-123"
    assert fake_app.calls == [{"user_assertion": "token-b-value", "scopes": ["api://banking/.default"]}]
    assert [event[0] for event in events] == ["token_c_obo_completed"]


def test_token_c_obo_mode_requests_single_default_scope_for_read_and_write(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _configure_obo_env(monkeypatch, tmp_path)
    monkeypatch.setenv("ENTRA_BANKING_SCOPES", "api://banking/Banking.Read, api://banking/Banking.Write api://banking/Banking.Read")
    token_state = set_delegated_token_b("token-b-value")
    fake_app = FakeOboApp(
        client_id="agent-b-client-id",
        client_credential="client-secret-value",
        authority="https://login.microsoftonline.com/tenant-123",
    )
    monkeypatch.setattr(token_c_provider.msal, "ConfidentialClientApplication", lambda **kwargs: fake_app)
    monkeypatch.setattr(token_c_provider, "log_flow_event", lambda *args, **kwargs: None)

    try:
        token = asyncio.run(token_c_provider.resolve_agent_b_token_c())
    finally:
        reset_delegated_token_b(token_state)

    assert token == "token-c-obo"
    assert fake_app.calls == [{"user_assertion": "token-b-value", "scopes": ["api://banking/.default"]}]


@pytest.mark.parametrize(
    "configured",
    [
        "api://banking-a/Banking.Read api://banking-b/Banking.Write",
        "Banking.Read Banking.Write",
        "api://banking/",
        "api:///Banking.Read",
        "api://banking/.default",
    ],
)
def test_token_c_obo_mode_fails_closed_on_mixed_or_malformed_scopes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, configured: str
) -> None:
    _configure_obo_env(monkeypatch, tmp_path)
    monkeypatch.setenv("ENTRA_BANKING_SCOPES", configured)
    token_state = set_delegated_token_b("token-b-secret")
    monkeypatch.setattr(token_c_provider, "log_flow_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(token_c_provider.msal, "ConfidentialClientApplication", lambda **kwargs: pytest.fail("MSAL must not run"))

    try:
        with pytest.raises(token_c_provider.TokenCResolutionError) as exc_info:
            asyncio.run(token_c_provider.resolve_agent_b_token_c())
    finally:
        reset_delegated_token_b(token_state)

    assert exc_info.value.category == "invalid_configuration"
    message = str(exc_info.value)
    assert "banking" not in message.lower() and "token-b-secret" not in message


def test_token_c_obo_mode_fails_closed_without_token_b(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _configure_obo_env(monkeypatch, tmp_path)
    set_flow_id("flow-obo-2")
    events: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(token_c_provider.msal, "ConfidentialClientApplication", lambda **kwargs: pytest.fail("MSAL should not be initialized without Token B"))
    monkeypatch.setattr(token_c_provider, "log_flow_event", lambda name, **kwargs: events.append((name, dict(kwargs))))

    with pytest.raises(token_c_provider.TokenCResolutionError, match="missing request-scoped Token B") as exc_info:
        asyncio.run(token_c_provider.resolve_agent_b_token_c())

    assert exc_info.value.category == "missing_token_b"
    assert [event[0] for event in events] == ["token_c_obo_failed"]


def test_token_c_obo_mode_rejects_bad_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_B_TOKEN_C_MODE", "obo")
    monkeypatch.delenv("ENTRA_TENANT_ID", raising=False)
    monkeypatch.delenv("ENTRA_AGENT_B_CLIENT_ID", raising=False)
    monkeypatch.delenv("ENTRA_AGENT_B_CLIENT_SECRET_FILE", raising=False)
    monkeypatch.delenv("ENTRA_BANKING_SCOPES", raising=False)
    monkeypatch.delenv("ENTRA_BANKING_SCOPE", raising=False)

    with pytest.raises(token_c_provider.TokenCResolutionError, match="incomplete") as exc_info:
        asyncio.run(token_c_provider.resolve_agent_b_token_c())

    assert exc_info.value.category == "missing_configuration"


def test_token_c_obo_mode_sanitizes_msal_errors(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _configure_obo_env(monkeypatch, tmp_path)
    set_flow_id("flow-obo-3")
    token_state = set_delegated_token_b("token-b-secret")
    monkeypatch.setattr(token_c_provider, "log_flow_event", lambda *args, **kwargs: None)

    class FailingOboApp:
        def __init__(self, *, client_id: str, client_credential: str, authority: str):
            self.client_id = client_id
            self.client_credential = client_credential
            self.authority = authority

        def acquire_token_on_behalf_of(self, *, user_assertion: str, scopes: list[str]) -> dict[str, str]:
            raise RuntimeError(f"raw failure {user_assertion} {scopes} {self.client_credential}")

    monkeypatch.setattr(token_c_provider.msal, "ConfidentialClientApplication", lambda **kwargs: FailingOboApp(**kwargs))

    try:
        with pytest.raises(token_c_provider.TokenCResolutionError, match="MSAL exchange failed") as exc_info:
            asyncio.run(token_c_provider.resolve_agent_b_token_c())
    finally:
        reset_delegated_token_b(token_state)

    message = str(exc_info.value)
    assert "token-b-secret" not in message
    assert "client-secret-value" not in message


def test_agent_b_mcp_client_uses_obo_token_in_authorization_header(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _configure_obo_env(monkeypatch, tmp_path)
    set_flow_id("flow-obo-4")
    token_state = set_delegated_token_b("token-b-for-mcp")

    fake_app = FakeOboApp(client_id="agent-b-client-id", client_credential="client-secret-value", authority="https://login.microsoftonline.com/tenant-123")
    monkeypatch.setattr(token_c_provider.msal, "ConfidentialClientApplication", lambda **kwargs: fake_app)

    responses = [
        FakeResponse(headers={"Mcp-Session-Id": "sess-obo"}, text=_sse_body({"jsonrpc": "2.0", "result": {"protocolVersion": "2025-03-26", "capabilities": {}, "serverInfo": {"name": "banking-mcp", "version": "1.0.0"}}})),
        FakeResponse(status_code=202, text=""),
        FakeResponse(text=_sse_body({"jsonrpc": "2.0", "result": {"tools": [{"name": "get_account_summary", "description": "Read a balance"}]}})),
        FakeResponse(text=_sse_body({"jsonrpc": "2.0", "result": {"content": [{"type": "text", "text": "Balance for acct-1001 is 12345.67"}]}})),
    ]
    fake_client = FakeAsyncClient(responses)
    monkeypatch.setattr(mcp_client.httpx, "AsyncClient", lambda *args, **kwargs: fake_client)

    try:
        result = asyncio.run(mcp_client.get_account_summary("acct-1001"))
    finally:
        reset_delegated_token_b(token_state)

    assert result == "Balance for acct-1001 is 12345.67"
    assert [call["json"]["method"] for call in fake_client.calls] == ["initialize", "notifications/initialized", "tools/list", "tools/call"]
    assert fake_client.calls[0]["headers"]["Authorization"] == "Bearer token-c-obo"
    assert fake_client.calls[0]["headers"]["X-Flow-ID"] == "flow-obo-4"
    assert fake_client.calls[1]["headers"]["Mcp-Session-Id"] == "sess-obo"
    assert fake_client.calls[1]["headers"]["X-Flow-ID"] == "flow-obo-4"
    assert fake_client.calls[2]["headers"]["Authorization"] == "Bearer token-c-obo"
    assert fake_client.calls[3]["headers"]["Authorization"] == "Bearer token-c-obo"


def test_agent_b_mcp_client_fails_before_network_when_token_b_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _configure_obo_env(monkeypatch, tmp_path)
    set_flow_id("flow-obo-5")
    monkeypatch.delenv("TOKEN_C_FILE", raising=False)

    called = []

    class FailingClient:
        def __init__(self, *args, **kwargs):
            called.append(True)
            raise AssertionError("MCP HTTP client should not be created when Token B is missing")

    monkeypatch.setattr(mcp_client.httpx, "AsyncClient", FailingClient)

    with pytest.raises(RuntimeError, match="missing request-scoped Token B"):
        asyncio.run(mcp_client.get_account_summary("acct-1001"))

    assert called == []


def test_token_c_obo_mode_supports_authorized_create_transfer(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _configure_obo_env(monkeypatch, tmp_path)
    monkeypatch.setenv("ENTRA_BANKING_SCOPES", "api://banking/Banking.Read api://banking/Banking.Write")
    set_flow_id("flow-obo-6")
    token_state = set_delegated_token_b("token-b-for-denied-write")

    fake_app = FakeOboApp(client_id="agent-b-client-id", client_credential="client-secret-value", authority="https://login.microsoftonline.com/tenant-123")
    monkeypatch.setattr(token_c_provider.msal, "ConfidentialClientApplication", lambda **kwargs: fake_app)

    responses = [
        FakeResponse(headers={"Mcp-Session-Id": "sess-denied"}, text=_sse_body({"jsonrpc": "2.0", "result": {"protocolVersion": "2025-03-26", "capabilities": {}, "serverInfo": {"name": "banking-mcp", "version": "1.0.0"}}})),
        FakeResponse(status_code=202, text=""),
        FakeResponse(text=_sse_body({"jsonrpc": "2.0", "result": {"tools": [{"name": "create_transfer"}, {"name": "get_account_summary"}]}})),
        FakeResponse(text=_sse_body({"jsonrpc": "2.0", "result": {"content": [{"type": "text", "text": "Transfer created for acct-2002 amount 25.00"}]}})),
    ]
    fake_client = FakeAsyncClient(responses)
    monkeypatch.setattr(mcp_client.httpx, "AsyncClient", lambda *args, **kwargs: fake_client)

    try:
        result = asyncio.run(
            mcp_client.create_transfer(
                "acct-1001",
                "acct-2002",
                25.0,
                "yes",
                "obo-transfer-1",
            )
        )
    finally:
        reset_delegated_token_b(token_state)

    assert result == "Transfer created for acct-2002 amount 25.00"
    assert fake_client.calls[-1]["headers"]["X-Idempotency-Key"] == "obo-transfer-1"
    assert fake_client.calls[-1]["headers"]["Authorization"] == "Bearer token-c-obo"


def test_a2a_boundary_captures_and_resets_delegated_token(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(a2a_server, "log_flow_event", lambda name, **kwargs: events.append((name, dict(kwargs))))
    monkeypatch.setattr(a2a_server, "set_flow_id", lambda flow_id: None)

    async def app(scope, receive, send):
        assert get_delegated_token_b() == "token-b-a2a"
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok", "more_body": False})

    wrapped = a2a_server._with_a2a_flow_logging(app)

    async def run_request():
        scope = {
            "type": "http",
            "path": "/agents/messages",
            "headers": [(b"authorization", b"Bearer token-b-a2a"), (b"x-flow-id", b"flow-a2a-1")],
        }
        messages = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            messages.append(message)

        await wrapped(scope, receive, send)
        return messages

    assert asyncio.run(run_request())[-1]["type"] == "http.response.body"
    assert get_delegated_token_b() is None
    assert [event[0] for event in events] == [
        "agent_b.delegated_token.received",
        "agent_b.a2a.request.received",
        "agent_b.a2a.response.completed",
    ]
    delegated_event = events[0][1]
    assert delegated_event["flow_id"] == "flow-a2a-1"
    assert delegated_event["delegated_token_present"] is True
    assert "token-b-a2a" not in repr(delegated_event)


def test_a2a_boundary_skips_agent_card_token_capture(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(a2a_server, "log_flow_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(a2a_server, "set_flow_id", lambda flow_id: None)

    async def app(scope, receive, send):
        assert get_delegated_token_b() is None
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok", "more_body": False})

    wrapped = a2a_server._with_a2a_flow_logging(app)

    async def run_request():
        scope = {
            "type": "http",
            "path": "/.well-known/agent-card.json",
            "headers": [(b"authorization", b"Bearer token-b-a2a"), (b"x-flow-id", b"flow-a2a-2")],
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            return None

        await wrapped(scope, receive, send)

    asyncio.run(run_request())
    assert get_delegated_token_b() is None


def test_a2a_boundary_resets_token_even_when_inner_app_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(a2a_server, "log_flow_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(a2a_server, "set_flow_id", lambda flow_id: None)

    async def app(scope, receive, send):
        assert get_delegated_token_b() == "token-b-failure"
        raise RuntimeError("boom")

    wrapped = a2a_server._with_a2a_flow_logging(app)

    async def run_request():
        scope = {
            "type": "http",
            "path": "/agents/messages",
            "headers": [(b"authorization", b"Bearer token-b-failure"), (b"x-flow-id", b"flow-a2a-3")],
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            return None

        with pytest.raises(RuntimeError, match="boom"):
            await wrapped(scope, receive, send)

    asyncio.run(run_request())
    assert get_delegated_token_b() is None


def test_delegated_token_context_isolated_between_tasks() -> None:
    async def worker(token_value: str) -> str | None:
        token = set_delegated_token_b(token_value)
        try:
            await asyncio.sleep(0)
            return get_delegated_token_b()
        finally:
            reset_delegated_token_b(token)

    async def run_workers():
        results = await asyncio.gather(worker("token-a"), worker("token-b"))
        return results

    assert asyncio.run(run_workers()) == ["token-a", "token-b"]
    assert get_delegated_token_b() is None


def test_poc_raw_user_identity_logging_is_guarded_by_exact_env_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    import jwt

    from agents import flow_logging

    token = jwt.encode(
        {
            "oid": "user-12345",
            "tid": "tenant-123",
            "preferred_username": "test.user@example.com",
        },
        key="test-only-secret-that-is-longer-than-thirty-two-bytes",
        algorithm="HS256",
    )
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(flow_logging, "log_flow_event", lambda *args, **kwargs: calls.append({"args": args, "kwargs": kwargs}))
    monkeypatch.delenv("POC_LOG_RAW_USER_ID", raising=False)

    flow_logging.log_raw_user_identity("poc.identity.debug", component="unit-test", token=token)
    assert calls == []

    monkeypatch.setenv("POC_LOG_RAW_USER_ID", "true")
    calls.clear()
    flow_logging.log_raw_user_identity("poc.identity.debug", component="unit-test", token=token)

    assert len(calls) == 1
    payload = calls[0]["kwargs"]
    assert payload["oid"] == "user-12345"
    assert payload["tid"] == "tenant-123"
    assert payload["preferred_username"] == "test.user@example.com"
    assert "token" not in repr(payload)
    assert "secret" not in repr(payload)


__all__ = [
    "test_token_c_file_mode_is_default_and_skips_msal",
    "test_token_c_obo_mode_uses_request_scoped_token_b",
    "test_token_c_obo_mode_requests_distinct_read_and_write_scopes",
    "test_token_c_obo_mode_fails_closed_without_token_b",
    "test_token_c_obo_mode_rejects_bad_configuration",
    "test_token_c_obo_mode_sanitizes_msal_errors",
    "test_agent_b_mcp_client_uses_obo_token_in_authorization_header",
    "test_agent_b_mcp_client_fails_before_network_when_token_b_missing",
    "test_token_c_obo_mode_supports_authorized_create_transfer",
    "test_a2a_boundary_captures_and_resets_delegated_token",
    "test_a2a_boundary_skips_agent_card_token_capture",
    "test_a2a_boundary_resets_token_even_when_inner_app_fails",
    "test_delegated_token_context_isolated_between_tasks",
]
