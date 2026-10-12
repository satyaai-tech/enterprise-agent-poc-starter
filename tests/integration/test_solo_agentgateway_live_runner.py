from __future__ import annotations

import base64
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[2] / "experiments" / "solo-agentgateway" / "a2a-obo" / "live_a2a_obo.py"
SPEC = importlib.util.spec_from_file_location("solo_live_runner", MODULE_PATH)
assert SPEC and SPEC.loader
live_a2a_obo = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(live_a2a_obo)


class FakePublicClient:
    def __init__(self, *, client_id: str, authority: str):
        self.client_id = client_id
        self.authority = authority

    def initiate_device_flow(self, *, scopes: list[str]) -> dict[str, str]:
        return {
            "message": "Enter the code below",
            "verification_uri": "https://microsoft.com/devicelogin",
            "user_code": "ABCD-12345",
        }

    def acquire_token_by_device_flow(self, flow: dict[str, str]) -> dict[str, str]:
        return {"access_token": "token-a"}


class FakeConfidentialClient:
    def __init__(self, *, client_id: str, client_credential: str, authority: str):
        self.client_id = client_id
        self.client_credential = client_credential
        self.authority = authority

    def acquire_token_on_behalf_of(self, *, user_assertion: str, scopes: list[str]) -> dict[str, str]:
        return {"access_token": "token-b"}


def test_live_runner_requires_live_flag() -> None:
    with pytest.raises(SystemExit):
        live_a2a_obo.main([])


def test_compare_user_continuity_uses_oid_and_tid() -> None:
    def make_token(oid: str, tid: str, sub: str) -> str:
        payload = {"oid": oid, "tid": tid, "sub": sub}
        encoded = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8")).rstrip(b"=").decode("ascii")
        return f"eyJhbGciOiJub25lIn0.{encoded}."

    token_a = make_token("user-1", "tenant-123", "subject-a")
    token_b = make_token("user-1", "tenant-123", "subject-b")
    token_c = make_token("user-2", "tenant-123", "subject-c")

    assert live_a2a_obo.compare_user_continuity(token_a, token_b) is True
    assert live_a2a_obo.compare_user_continuity(token_a, token_c) is False


def test_live_compose_definition_is_valid_and_has_no_fixture() -> None:
    compose_text = (live_a2a_obo.SPIKE_DIR / "compose.live.yaml").read_text(encoding="utf-8")
    assert "services:" in compose_text
    assert "mock-agent-b" in compose_text
    assert "agentgateway" in compose_text
    assert "solo-a2a-live" in compose_text
    assert "ports:" in compose_text
    assert "jwks-fixture" not in compose_text.lower()
    assert compose_text.count("ports:") == 1


def test_minimal_subprocess_env_keeps_safe_runtime_values_and_excludes_secrets() -> None:
    env = live_a2a_obo.build_minimal_subprocess_env(
        extra={
            "PATH": "/usr/local/bin:/usr/bin",
            "HOME": "/Users/test-user",
            "TMPDIR": "/var/folders/test",
            "DOCKER_HOST": "unix:///var/run/docker.sock",
            "DOCKER_CONTEXT": "default",
            "DOCKER_CONFIG": "/Users/test-user/.docker",
            "XDG_CONFIG_HOME": "/Users/test-user/.config",
            "TENANT_ID": "tenant-123",
            "ISSUER": "https://login.microsoftonline.com/tenant-123/v2.0",
            "EXPECTED_AUDIENCE": "api://agent-b-example",
            "EXPECTED_SCOPE": "AgentB.Access",
            "AUTHORIZED_CLIENT": "agent-a-client",
            "JWKS_URL": "https://example.test/jwks",
            "HOST_PORT": "18081",
            "AG_CONFIG_PATH": "/tmp/agentgateway-config.yaml",
            "ENTRA_AGENT_A_CLIENT_SECRET": "secret-value",
            "DEVICE_CODE": "abc",
            "ACCESS_TOKEN": "token",
            "AUTHORIZATION_CODE": "auth-code",
            "EXTRA": "keep me",
        }
    )
    assert env["PATH"] == "/usr/local/bin:/usr/bin"
    assert env["HOME"] == "/Users/test-user"
    assert env["TMPDIR"] == "/var/folders/test"
    assert env["DOCKER_HOST"] == "unix:///var/run/docker.sock"
    assert env["DOCKER_CONTEXT"] == "default"
    assert env["DOCKER_CONFIG"] == "/Users/test-user/.docker"
    assert env["XDG_CONFIG_HOME"] == "/Users/test-user/.config"
    assert env["TENANT_ID"] == "tenant-123"
    assert "ENTRA_AGENT_A_CLIENT_SECRET" not in env
    assert "DEVICE_CODE" not in env
    assert "ACCESS_TOKEN" not in env
    assert "AUTHORIZATION_CODE" not in env
    assert "EXTRA" not in env


def test_live_runner_uses_sys_executable_and_resolves_docker(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(live_a2a_obo, "EVIDENCE_DIR", tmp_path / "evidence" / "solo-phase-2")
    monkeypatch.setattr(live_a2a_obo, "load_env_file", lambda: None)
    monkeypatch.setattr(
        live_a2a_obo,
        "get_runtime_config",
        lambda: {
            "ENTRA_TENANT_ID": "tenant-123",
            "ENTRA_NOTEBOOK_CLIENT_ID": "notebook-client",
            "ENTRA_AGENT_A_SCOPE": "api://agent-a/AgentA.Access",
            "ENTRA_AGENT_A_CLIENT_ID": "agent-a-client",
            "ENTRA_AGENT_A_CLIENT_SECRET": "secret",
            "ENTRA_AGENT_A_EXPECTED_AUDIENCE": "api://agent-a-example",
            "ENTRA_AGENT_B_SCOPE": "api://agent-b/AgentB.Access",
            "ENTRA_AGENT_B_EXPECTED_AUDIENCE": "api://agent-b-example",
        },
    )
    monkeypatch.setattr(live_a2a_obo, "resolve_issuer_and_jwks", lambda tenant_id, token: ("https://login.microsoftonline.com/tenant-123/v2.0", "https://example.test/jwks"))
    monkeypatch.setattr(live_a2a_obo, "compare_user_continuity", lambda token_a, token_b: True)
    monkeypatch.setattr(live_a2a_obo, "validate_token_for_policy", lambda *args, **kwargs: {"result": "PASS", "error_category": "NONE"})
    monkeypatch.setattr(live_a2a_obo.msal, "PublicClientApplication", FakePublicClient)
    monkeypatch.setattr(live_a2a_obo.msal, "ConfidentialClientApplication", FakeConfidentialClient)
    monkeypatch.setattr(live_a2a_obo, "wait_for_gateway_ready", lambda *args, **kwargs: None)
    monkeypatch.setattr(live_a2a_obo, "choose_host_port", lambda: 18081)
    monkeypatch.setattr(shutil, "which", lambda name, path=None: "/usr/local/bin/docker")

    commands: list[list[str]] = []

    def fake_run(command: list[str], **kwargs):
        commands.append(command)
        return None

    monkeypatch.setattr(live_a2a_obo.subprocess, "run", fake_run)

    def fake_request_json(url: str, **kwargs):
        token = kwargs.get("token")
        if url.endswith("/.well-known/agent.json"):
            return (200, {"name": "mock-agent-b"})
        if url.endswith("__debug/requests"):
            return (200, {"protected_message_count": 1})
        if url.endswith("a2a"):
            if token == "token-a":
                return (401, {"jsonrpc": "2.0", "error": {"code": -32001, "message": "Unauthorized"}})
            return (200, {"result": {"kind": "message", "metadata": {"audience_ok": True, "client_ok": True, "issuer_ok": True, "tenant_ok": True, "scope_ok": True}}})
        return (200, {})

    monkeypatch.setattr(live_a2a_obo, "request_json", fake_request_json)
    rc = live_a2a_obo.main(["--live"])

    assert rc == 0
    render_run = next(cmd for cmd in commands if cmd and cmd[0] == sys.executable and cmd[-1].endswith("render_config.py"))
    assert render_run[0] == sys.executable
    assert any(cmd and cmd[0] == "/usr/local/bin/docker" and cmd[1] == "compose" for cmd in commands)


def test_missing_docker_executable_fails_safely(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name, path=None: None)
    with pytest.raises(RuntimeError, match="Docker executable not found"):
        live_a2a_obo.resolve_docker_executable({"PATH": "/usr/bin"})


def test_live_runner_success_path_and_token_a_rejection(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(live_a2a_obo, "EVIDENCE_DIR", tmp_path / "evidence" / "solo-phase-2")
    monkeypatch.setattr(live_a2a_obo, "load_env_file", lambda: None)
    monkeypatch.setattr(
        live_a2a_obo,
        "get_runtime_config",
        lambda: {
            "ENTRA_TENANT_ID": "tenant-123",
            "ENTRA_NOTEBOOK_CLIENT_ID": "notebook-client",
            "ENTRA_AGENT_A_SCOPE": "api://agent-a/AgentA.Access",
            "ENTRA_AGENT_A_CLIENT_ID": "agent-a-client",
            "ENTRA_AGENT_A_CLIENT_SECRET": "secret",
            "ENTRA_AGENT_A_EXPECTED_AUDIENCE": "api://agent-a-example",
            "ENTRA_AGENT_B_SCOPE": "api://agent-b/AgentB.Access",
            "ENTRA_AGENT_B_EXPECTED_AUDIENCE": "api://agent-b-example",
        },
    )
    monkeypatch.setattr(live_a2a_obo, "resolve_issuer_and_jwks", lambda tenant_id, token: ("https://login.microsoftonline.com/tenant-123/v2.0", "https://example.test/jwks"))
    monkeypatch.setattr(live_a2a_obo, "compare_user_continuity", lambda token_a, token_b: True)
    monkeypatch.setattr(live_a2a_obo, "validate_token_for_policy", lambda *args, **kwargs: {"result": "PASS", "error_category": "NONE"})
    monkeypatch.setattr(live_a2a_obo.msal, "PublicClientApplication", FakePublicClient)
    monkeypatch.setattr(live_a2a_obo.msal, "ConfidentialClientApplication", FakeConfidentialClient)
    monkeypatch.setattr(live_a2a_obo, "wait_for_gateway_ready", lambda *args, **kwargs: None)

    calls: list[str] = []

    def fake_run(command: list[str], **kwargs):
        calls.append(command[-1] if command else "")
        return None

    monkeypatch.setattr(live_a2a_obo.subprocess, "run", fake_run)

    def fake_request_json(url: str, **kwargs):
        token = kwargs.get("token")
        if url.endswith("/.well-known/agent.json"):
            return (200, {"name": "mock-agent-b"})
        if url.endswith("__debug/requests"):
            return (200, {"protected_message_count": 1})
        if url.endswith("a2a"):
            if token == "token-a":
                return (401, {"jsonrpc": "2.0", "error": {"code": -32001, "message": "Unauthorized"}})
            return (200, {"result": {"kind": "message", "metadata": {"audience_ok": True, "client_ok": True, "issuer_ok": True, "tenant_ok": True, "scope_ok": True}}})
        return (200, {})

    monkeypatch.setattr(live_a2a_obo, "request_json", fake_request_json)
    rc = live_a2a_obo.main(["--live"])

    assert rc == 0
    files = list((tmp_path / "evidence" / "solo-phase-2").glob("*.json"))
    assert files
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert payload["status"] == "PASS"
    assert payload["device_login_completed"] is True
    assert payload["token_a_rejected_at_agent_b_boundary"] is True
    assert "token-a" not in json.dumps(payload).lower()
    assert "token-b" not in json.dumps(payload).lower()
    assert "sub" not in json.dumps(payload).lower()
    assert "oid" not in json.dumps(payload).lower()
    assert "secret" not in json.dumps(payload).lower()
    assert "docker" in " ".join(calls).lower() or calls


def test_cleanup_runs_after_partial_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(live_a2a_obo, "EVIDENCE_DIR", tmp_path / "evidence" / "solo-phase-2")
    monkeypatch.setattr(live_a2a_obo, "load_env_file", lambda: None)
    monkeypatch.setattr(
        live_a2a_obo,
        "get_runtime_config",
        lambda: {
            "ENTRA_TENANT_ID": "tenant-123",
            "ENTRA_NOTEBOOK_CLIENT_ID": "notebook-client",
            "ENTRA_AGENT_A_SCOPE": "api://agent-a/AgentA.Access",
            "ENTRA_AGENT_A_CLIENT_ID": "agent-a-client",
            "ENTRA_AGENT_A_CLIENT_SECRET": "secret",
            "ENTRA_AGENT_A_EXPECTED_AUDIENCE": "api://agent-a-example",
            "ENTRA_AGENT_B_SCOPE": "api://agent-b/AgentB.Access",
            "ENTRA_AGENT_B_EXPECTED_AUDIENCE": "api://agent-b-example",
        },
    )
    monkeypatch.setattr(live_a2a_obo, "resolve_issuer_and_jwks", lambda tenant_id, token: ("https://login.microsoftonline.com/tenant-123/v2.0", "https://example.test/jwks"))
    monkeypatch.setattr(live_a2a_obo, "compare_user_continuity", lambda token_a, token_b: True)
    monkeypatch.setattr(live_a2a_obo, "validate_token_for_policy", lambda *args, **kwargs: {"result": "PASS", "error_category": "NONE"})
    monkeypatch.setattr(live_a2a_obo.msal, "PublicClientApplication", FakePublicClient)
    monkeypatch.setattr(live_a2a_obo.msal, "ConfidentialClientApplication", FakeConfidentialClient)
    monkeypatch.setattr(live_a2a_obo, "wait_for_gateway_ready", lambda *args, **kwargs: None)
    monkeypatch.setattr(live_a2a_obo, "choose_host_port", lambda: 18081)
    monkeypatch.setattr(shutil, "which", lambda name, path=None: "/usr/local/bin/docker")

    shutdown_calls: list[str] = []

    def fake_run(command: list[str], **kwargs):
        if command[:3] == ["/usr/local/bin/docker", "compose", "-f"] and "down" in command:
            shutdown_calls.append("down")
        return None

    monkeypatch.setattr(live_a2a_obo.subprocess, "run", fake_run)

    def fake_request_json(url: str, **kwargs):
        if url.endswith("/.well-known/agent.json"):
            return (200, {"name": "mock-agent-b"})
        if url.endswith("a2a"):
            raise RuntimeError("partial failure")
        return (200, {"protected_message_count": 1})

    monkeypatch.setattr(live_a2a_obo, "request_json", fake_request_json)

    rc = live_a2a_obo.main(["--live"])

    assert rc == 1
    assert shutdown_calls == ["down"]


def test_evidence_file_refuses_overwrite(tmp_path: Path) -> None:
    path = tmp_path / "evidence.json"
    live_a2a_obo.write_evidence_file({"status": "PASS", "error_category": "NONE", "timestamp_utc": "2026-10-11T00:00:00Z"}, path=path)
    with pytest.raises(FileExistsError):
        live_a2a_obo.write_evidence_file({"status": "FAIL", "error_category": "NONE", "timestamp_utc": "2026-10-11T00:00:00Z"}, path=path)


def test_live_runner_uses_guarded_helpers_without_env_access(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, bool] = {"env": False}

    def fake_load_env() -> None:
        called["env"] = True

    monkeypatch.setattr(live_a2a_obo, "load_env_file", fake_load_env)
    monkeypatch.setattr(live_a2a_obo, "get_runtime_config", lambda: {
        "ENTRA_TENANT_ID": "tenant-123",
        "ENTRA_NOTEBOOK_CLIENT_ID": "notebook-client",
        "ENTRA_AGENT_A_SCOPE": "api://agent-a/AgentA.Access",
        "ENTRA_AGENT_A_CLIENT_ID": "agent-a-client",
        "ENTRA_AGENT_A_CLIENT_SECRET": "secret",
        "ENTRA_AGENT_A_EXPECTED_AUDIENCE": "api://agent-a-example",
        "ENTRA_AGENT_B_SCOPE": "api://agent-b/AgentB.Access",
        "ENTRA_AGENT_B_EXPECTED_AUDIENCE": "api://agent-b-example",
    })
    monkeypatch.setattr(live_a2a_obo, "msal", type("M", (), {"PublicClientApplication": FakePublicClient, "ConfidentialClientApplication": FakeConfidentialClient}))
    monkeypatch.setattr(live_a2a_obo, "resolve_issuer_and_jwks", lambda tenant_id, token: ("https://login.microsoftonline.com/tenant-123/v2.0", "https://example.test/jwks"))
    monkeypatch.setattr(live_a2a_obo, "compare_user_continuity", lambda token_a, token_b: True)
    monkeypatch.setattr(live_a2a_obo, "validate_token_for_policy", lambda *args, **kwargs: {"result": "PASS", "error_category": "NONE"})
    monkeypatch.setattr(live_a2a_obo, "request_json", lambda *args, **kwargs: (200, {"name": "mock-agent-b"}))
    monkeypatch.setattr(live_a2a_obo, "wait_for_gateway_ready", lambda *args, **kwargs: None)
    monkeypatch.setattr(live_a2a_obo, "choose_host_port", lambda: 18081)
    monkeypatch.setattr(live_a2a_obo.subprocess, "run", lambda *args, **kwargs: None)

    with pytest.raises(SystemExit):
        live_a2a_obo.main([])
    assert called["env"] is False
