from __future__ import annotations

import importlib.util
import io
import json
import os
import re
import socket
import subprocess
import time
import urllib.request
from urllib.parse import urlparse
import uuid
from datetime import datetime, timezone
from pathlib import Path

import jwt
import pytest
import yaml
from cryptography.hazmat.primitives.asymmetric import rsa

REPO_ROOT = Path(__file__).resolve().parents[2]
PROFILE_DIR = REPO_ROOT / "experiments" / "solo-agentgateway" / "unified"
COMPOSE_FILE = PROFILE_DIR / "compose.yaml"
RENDERER_PATH = PROFILE_DIR / "render_config.py"
UNIFIED_LOCAL_IMAGES = (
    "solo-agentgateway-unified-jwks-fixture:local",
    "solo-agentgateway-unified-agent-a:local",
    "solo-agentgateway-unified-agent-b:local",
    "solo-agentgateway-unified-banking-mcp:local",
)

LIVE_UNIFIED_MODULE = importlib.util.spec_from_file_location(
    "live_unified_obo",
    REPO_ROOT / "experiments" / "solo-agentgateway" / "unified" / "live_unified_obo.py",
)
assert LIVE_UNIFIED_MODULE and LIVE_UNIFIED_MODULE.loader
live_unified_obo = importlib.util.module_from_spec(LIVE_UNIFIED_MODULE)
LIVE_UNIFIED_MODULE.loader.exec_module(live_unified_obo)
LIVE_COMPOSE_FILE = PROFILE_DIR / "compose.live.yaml"


def _load_renderer():
    spec = importlib.util.spec_from_file_location("unified_render_config", RENDERER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _compose(env: dict[str, str], *args: str, check: bool = True):
    return subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), *args],
        cwd=REPO_ROOT,
        env=env,
        check=check,
        capture_output=True,
        text=True,
    )


def _wait(url: str, timeout: float = 90.0, headers: dict[str, str] | None = None) -> bytes:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            request = urllib.request.Request(url, headers=headers or {})
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.read()
        except Exception as exc:  # pragma: no cover - diagnostics retained by timeout
            last_error = exc
            time.sleep(1)
    raise RuntimeError(f"Timed out waiting for {url}: {last_error}")


def _write_public_jwks(tmp_path: Path) -> tuple[Path, object]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(public_key))
    public_jwk["kid"] = "synthetic-kid"

    jwks_dir = tmp_path / "jwks"
    jwks_dir.mkdir(parents=True, exist_ok=True)
    jwks_path = jwks_dir / "jwks.json"
    jwks_path.write_text(json.dumps({"keys": [public_jwk]}, indent=2), encoding="utf-8")
    return jwks_path, private_key


def _build_token_a(private_key, issuer: str) -> str:
    now = int(datetime.now(timezone.utc).timestamp())
    payload = {
        "iss": issuer,
        "aud": "api://agent-a-example",
        "tid": "11111111-2222-3333-4444-555555666666",
        "scp": "AgentA.Access",
        "sub": "user-12345",
        "oid": "user-12345",
        "iat": now - 60,
        "nbf": now - 30,
        "exp": now + 300,
        "ver": "2.0",
        "azp": "synthetic-agent-a",
    }
    return jwt.encode(payload, private_key, algorithm="RS256", headers={"kid": "synthetic-kid"})


def _build_token_for_scope(
    private_key,
    issuer: str,
    *,
    audience: str,
    scope: str,
    authorized_client: str,
    client_claim: str = "azp",
    roles: list[str] | None = None,
) -> str:
    now = int(datetime.now(timezone.utc).timestamp())
    payload = {
        "iss": issuer,
        "aud": audience,
        "tid": "11111111-2222-3333-4444-555555666666",
        "scp": scope,
        "sub": "user-12345",
        "oid": "user-12345",
        "iat": now - 60,
        "nbf": now - 30,
        "exp": now + 300,
        "ver": "2.0",
        client_claim: authorized_client,
    }
    if roles is not None:
        payload["roles"] = list(roles)
    elif audience == "api://banking-mock":
        payload["roles"] = ["Banking.Reader"]
    return jwt.encode(payload, private_key, algorithm="RS256", headers={"kid": "synthetic-kid"})


def _require_ollama_model(model_name: str = "qwen3:8b") -> None:
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # pragma: no cover - intentionally fails fast in a real environment
        raise RuntimeError(f"Local Ollama unavailable: {exc}") from exc

    models = payload.get("models", [])
    names = []
    for item in models:
        if isinstance(item, dict):
            names.append(str(item.get("name", "")))
    if not any(name == model_name or name.startswith(f"{model_name}:") for name in names):
        raise RuntimeError(f"Local Ollama model unavailable: {model_name}")


def _http_json(url: str, *, method: str = "GET", headers: dict[str, str] | None = None, payload: dict | None = None) -> tuple[int, dict | list | str, dict[str, str]]:
    request = urllib.request.Request(
        url,
        method=method,
        headers=headers or {},
        data=None if payload is None else json.dumps(payload).encode("utf-8"),
    )
    if payload is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body) if body else "", dict(response.headers)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise urllib.error.HTTPError(exc.url, exc.code, exc.reason, exc.headers, io.BytesIO(body.encode("utf-8"))) from exc


def _docker_compose(env: dict[str, str], *args: str, check: bool = True):
    return subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), *args],
        cwd=REPO_ROOT,
        env=env,
        check=check,
        capture_output=True,
        text=True,
    )


def _image_exists(image: str) -> bool:
    result = subprocess.run(
        ["docker", "image", "inspect", image],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _compose_up_wait_build_if_needed(env: dict[str, str], *, use_docker_compose: bool) -> None:
    requires_build = not all(_image_exists(image) for image in UNIFIED_LOCAL_IMAGES)
    up_args = ["up", "-d"]
    if requires_build:
        up_args.append("--build")
    up_args.append("--wait")

    if use_docker_compose:
        _docker_compose(env, *up_args)
    else:
        _compose(env, *up_args)


def _docker_exec(env: dict[str, str], service: str, command: str) -> str:
    result = subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "-p", env["COMPOSE_PROJECT_NAME"], "exec", "-T", service, "python", "-c", command],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _sanitize_log_text(text: str) -> str:
    sanitized = text
    for token in [
        "Bearer ",
        "eyJ",
        "-----BEGIN",
        "acct-",
        "user-",
        "synthetic-agent",
        "@example.com",
    ]:
        sanitized = sanitized.replace(token, "[redacted]")
    return sanitized


def test_live_unified_compose_config_renders_without_token_files_or_fixture(tmp_path):
    agent_a_secret = tmp_path / "agent-a-client-secret.txt"
    agent_b_secret = tmp_path / "agent-b-client-secret.txt"
    agent_a_secret.write_text("agent-a-client-secret-value\n", encoding="utf-8")
    agent_b_secret.write_text("agent-b-client-secret-value\n", encoding="utf-8")
    env = os.environ.copy()
    env.update(
        {
            "TENANT_ID": "11111111-2222-3333-4444-555555666666",
            "ISSUER": "https://login.microsoftonline.com/11111111-2222-3333-4444-555555666666/v2.0",
            "JWKS_URL": "https://login.microsoftonline.com/11111111-2222-3333-4444-555555666666/discovery/v2.0/keys",
            "API_AUDIENCE": "api://agent-a-example",
            "A2A_AUDIENCE": "api://agent-b-example",
            "MCP_AUDIENCE": "api://banking-mock",
            "API_SCOPE": "AgentA.Access",
            "A2A_SCOPE": "AgentB.Access",
            "BANKING_SCOPE": "Banking.Read Banking.Write",
            "API_AUTHORIZED_CLIENT": "synthetic-agent-a",
            "A2A_AUTHORIZED_CLIENT": "synthetic-agent-a",
            "MCP_AUTHORIZED_CLIENT": "synthetic-agent-b",
            "ENTRA_TENANT_ID": "11111111-2222-3333-4444-555555666666",
            "ENTRA_AGENT_A_CLIENT_ID": "agent-a-client-id",
            "ENTRA_AGENT_A_CLIENT_SECRET_FILE": str(agent_a_secret),
            "ENTRA_AGENT_B_SCOPE": "api://agent-b/AgentB.Access",
            "ENTRA_AGENT_B_CLIENT_ID": "agent-b-client-id",
            "ENTRA_AGENT_B_CLIENT_SECRET_FILE": str(agent_b_secret),
            "ENTRA_BANKING_SCOPE": "api://banking/Banking.Read",
            "ENTRA_BANKING_SCOPES": "api://banking/Banking.Read api://banking/Banking.Write",
            "BANKING_ACCOUNT_OWNERS_JSON": '{"acct-9000":"reader-oid","acct-1001":"writer-oid"}',
            "POC_LOG_RAW_USER_ID": "false",
            "AG_CONFIG_PATH": str(tmp_path / "agentgateway-config"),
            "API_HOST_PORT": "18080",
            "A2A_HOST_PORT": "18081",
            "MCP_HOST_PORT": "18082",
        }
    )

    result = subprocess.run(
        ["docker", "compose", "-f", str(LIVE_COMPOSE_FILE), "config", "--format", "json"],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    rendered = json.loads(result.stdout)

    agent_a_env = rendered["services"]["agent-a"]["environment"]
    agent_b_env = rendered["services"]["agent-b"]["environment"]
    banking_env = rendered["services"]["banking-mcp"]["environment"]
    agent_a_volumes = rendered["services"]["agent-a"]["volumes"]
    agent_b_volumes = rendered["services"]["agent-b"]["volumes"]
    gateway_ports = rendered["services"]["agentgateway"]["ports"]

    assert "TOKEN_B_FILE" not in agent_a_env
    assert "TOKEN_C_FILE" not in agent_b_env
    assert "jwks-fixture" not in rendered["services"]
    assert agent_b_env["AGENT_B_TOKEN_C_MODE"] == "obo"
    assert agent_b_env["ENTRA_BANKING_SCOPES"] == "api://banking/Banking.Read api://banking/Banking.Write"
    assert banking_env["EXPECTED_SCOPE"] == "Banking.Read Banking.Write"
    assert banking_env["BANKING_ACCOUNT_OWNERS_JSON"] == '{"acct-9000":"reader-oid","acct-1001":"writer-oid"}'
    assert agent_a_env["AGENT_A_TOKEN_B_MODE"] == "obo"
    assert any(
        volume.get("target") == "/run/secrets/agent-a-client-secret" and volume.get("read_only") is True
        for volume in agent_a_volumes
    )
    assert any(
        volume.get("target") == "/run/secrets/agent-b-client-secret" and volume.get("read_only") is True
        for volume in agent_b_volumes
    )
    assert "https://login.microsoftonline.com/11111111-2222-3333-4444-555555666666/v2.0" in str(agent_b_env)
    assert "https://login.microsoftonline.com/11111111-2222-3333-4444-555555666666/discovery/v2.0/keys" in str(agent_b_env)
    assert {(entry["host_ip"], entry["target"], entry["published"]) for entry in gateway_ports} == {
        ("127.0.0.1", 8080, "18080"),
        ("127.0.0.1", 8081, "18081"),
        ("127.0.0.1", 8082, "18082"),
    }
    assert "POC_LOG_RAW_USER_ID" in agent_b_env


def test_live_runtime_env_uses_validated_real_entra_mapping() -> None:
    real_config = {
        "ENTRA_TENANT_ID": "tenant-live-123",
        "ENTRA_NOTEBOOK_CLIENT_ID": "notebook-client-live",
        "ENTRA_AGENT_A_CLIENT_ID": "agent-a-client-live",
        "ENTRA_AGENT_A_CLIENT_SECRET_FILE": "/tmp/live-agent-a-secret",
        "ENTRA_AGENT_A_SCOPE": "api://agent-a/AgentA.Access",
        "ENTRA_AGENT_A_EXPECTED_AUDIENCE": "api://agent-a-live",
        "ENTRA_AGENT_B_CLIENT_ID": "agent-b-client-live",
        "ENTRA_AGENT_B_SCOPE": "api://agent-b/AgentB.Access",
        "ENTRA_AGENT_B_EXPECTED_AUDIENCE": "api://agent-b-live",
        "ENTRA_AGENT_B_CLIENT_SECRET_FILE": "/tmp/live-agent-b-secret",
        "ENTRA_BANKING_SCOPES": "api://banking/Banking.Read api://banking/Banking.Write",
        "ENTRA_BANKING_EXPECTED_AUDIENCE": "api://banking-live",
        "BANKING_TEST_USER_OID": "user-12345",
        "BANKING_ACCOUNT_OWNERS_JSON": '{"acct-1001":"reader-oid","acct-2002":"writer-oid"}',
    }

    env = live_unified_obo._compose_live_runtime_env(real_config)

    assert env["API_AUDIENCE"] == "api://agent-a-live"
    assert env["A2A_AUDIENCE"] == "api://agent-b-live"
    assert env["MCP_AUDIENCE"] == "api://banking-live"
    assert env["API_SCOPE"] == "AgentA.Access"
    assert env["A2A_SCOPE"] == "AgentB.Access"
    assert env["BANKING_SCOPE"] == "Banking.Read Banking.Write"
    assert env["API_AUTHORIZED_CLIENT"] == "notebook-client-live"
    assert env["A2A_AUTHORIZED_CLIENT"] == "agent-a-client-live"
    assert env["MCP_AUTHORIZED_CLIENT"] == "agent-b-client-live"
    assert env["BANKING_TEST_USER_OID"] == "user-12345"
    assert env["ENTRA_TENANT_ID"] == "tenant-live-123"
    assert env["ENTRA_AGENT_A_CLIENT_SECRET_FILE"] == "/tmp/live-agent-a-secret"
    assert env["AGENT_A_TOKEN_B_MODE"] == "obo"
    assert env["ENTRA_AGENT_B_CLIENT_ID"] == "agent-b-client-live"
    assert env["ENTRA_BANKING_SCOPE"] == "api://banking/Banking.Read"
    assert env["ENTRA_BANKING_SCOPES"] == "api://banking/Banking.Read api://banking/Banking.Write"
    assert env["BANKING_ACCOUNT_OWNERS_JSON"] == '{"acct-1001":"reader-oid","acct-2002":"writer-oid"}'
    assert env["ENTRA_AGENT_B_CLIENT_SECRET_FILE"] == "/tmp/live-agent-b-secret"
    assert env["AGENT_B_TOKEN_C_MODE"] == "obo"
    assert env["API_AUDIENCE"] != "api://agent-a-example"
    assert env["A2A_AUDIENCE"] != "api://agent-b-example"
    assert env["MCP_AUDIENCE"] != "api://banking-mock"
    assert env["A2A_AUTHORIZED_CLIENT"] != "synthetic-agent-a"
    assert env["MCP_AUTHORIZED_CLIENT"] != "synthetic-agent-b"


def test_live_runtime_env_fails_closed_when_real_mapping_is_missing() -> None:
    incomplete = {
        "ENTRA_TENANT_ID": "tenant-live-123",
        "ENTRA_NOTEBOOK_CLIENT_ID": "notebook-client-live",
        "ENTRA_AGENT_A_CLIENT_ID": "agent-a-client-live",
        "ENTRA_AGENT_A_CLIENT_SECRET_FILE": "/tmp/live-agent-a-secret",
        "ENTRA_AGENT_A_SCOPE": "api://agent-a/AgentA.Access",
        "ENTRA_AGENT_A_EXPECTED_AUDIENCE": "api://agent-a-live",
        "ENTRA_AGENT_B_CLIENT_ID": "agent-b-client-live",
        "ENTRA_AGENT_B_SCOPE": "api://agent-b/AgentB.Access",
        "ENTRA_AGENT_B_EXPECTED_AUDIENCE": "api://agent-b-live",
        "ENTRA_AGENT_B_CLIENT_SECRET_FILE": "/tmp/live-agent-b-secret",
        "ENTRA_BANKING_SCOPES": "api://banking/Banking.Read api://banking/Banking.Write",
    }

    with pytest.raises(RuntimeError, match="Missing validated live Entra mapping"):
        live_unified_obo._compose_live_runtime_env(incomplete)


def test_live_token_role_validation_requires_reader_and_can_forbid_writer() -> None:
    token = jwt.encode(
        {"roles": ["Banking.Reader"]},
        "not-a-live-secret-but-long-enough-for-test-only",
        algorithm="HS256",
    )

    live_unified_obo._require_token_roles(
        token,
        required={"Banking.Reader"},
        forbidden={"Banking.Writer"},
    )

    with pytest.raises(RuntimeError, match="missing required app role"):
        live_unified_obo._require_token_roles(token, required={"Banking.Writer"})


def test_live_runtime_env_preserves_slice5c_account_owner_map() -> None:
    real_config = {
        "ENTRA_TENANT_ID": "tenant-live-123",
        "ENTRA_NOTEBOOK_CLIENT_ID": "notebook-client-live",
        "ENTRA_AGENT_A_CLIENT_ID": "agent-a-client-live",
        "ENTRA_AGENT_A_CLIENT_SECRET_FILE": "/tmp/live-agent-a-secret",
        "ENTRA_AGENT_A_SCOPE": "api://agent-a/AgentA.Access",
        "ENTRA_AGENT_A_EXPECTED_AUDIENCE": "api://agent-a-live",
        "ENTRA_AGENT_B_CLIENT_ID": "agent-b-client-live",
        "ENTRA_AGENT_B_SCOPE": "api://agent-b/AgentB.Access",
        "ENTRA_AGENT_B_EXPECTED_AUDIENCE": "api://agent-b-live",
        "ENTRA_AGENT_B_CLIENT_SECRET_FILE": "/tmp/live-agent-b-secret",
        "ENTRA_BANKING_SCOPES": "api://banking/Banking.Read api://banking/Banking.Write",
        "ENTRA_BANKING_EXPECTED_AUDIENCE": "api://banking-live",
        "BANKING_ACCOUNT_OWNERS_JSON": '{"acct-9000":"reader-oid","acct-1001":"writer-oid"}',
    }

    env = live_unified_obo._compose_live_runtime_env(real_config)

    assert env["BANKING_ACCOUNT_OWNERS_JSON"] == '{"acct-9000":"reader-oid","acct-1001":"writer-oid"}'
    assert env["BANKING_SCOPE"] == "Banking.Read Banking.Write"


def test_unified_slice_5a_read_only_end_to_end(tmp_path, monkeypatch):
    _require_ollama_model("qwen3:8b")

    config_dir = tmp_path / "config"
    monkeypatch.setenv("AG_CONFIG_PATH", str(config_dir))
    _load_renderer().render()

    jwks_path, private_key = _write_public_jwks(tmp_path)
    assert jwks_path.exists()
    token_b_file = tmp_path / "token-b.txt"
    token_c_file = tmp_path / "token-c.txt"

    issuer = "https://login.microsoftonline.com/11111111-2222-3333-4444-555555666666/v2.0"
    token_a = _build_token_a(private_key, issuer)
    token_b = _build_token_for_scope(
        private_key,
        issuer,
        audience="api://agent-b-example",
        scope="AgentB.Access",
        authorized_client="synthetic-agent-a",
    )
    token_c = _build_token_for_scope(
        private_key,
        issuer,
        audience="api://banking-mock",
        scope="Banking.Read",
        authorized_client="synthetic-agent-b",
    )
    token_b_file.write_text(token_b, encoding="utf-8")
    token_c_file.write_text(token_c, encoding="utf-8")

    token_c_claims = jwt.decode(token_c, options={"verify_signature": False})
    assert token_c_claims["scp"] == "Banking.Read"
    assert "Banking.Write" not in token_c_claims["scp"]

    flow_id = "slice-5a-flow-123"
    api_port = _free_port()
    a2a_port = _free_port()
    mcp_port = _free_port()
    project_name = f"solo-slice-5a-{uuid.uuid4().hex[:8]}"

    env = os.environ.copy()
    env.update(
        {
            "COMPOSE_PROJECT_NAME": project_name,
            "AG_CONFIG_PATH": str(config_dir),
            "API_HOST_PORT": str(api_port),
            "A2A_HOST_PORT": str(a2a_port),
            "MCP_HOST_PORT": str(mcp_port),
            "TENANT_ID": "11111111-2222-3333-4444-555555666666",
            "ISSUER": issuer,
            "API_AUDIENCE": "api://agent-a-example",
            "A2A_AUDIENCE": "api://agent-b-example",
            "MCP_AUDIENCE": "api://banking-mock",
            "API_AUTHORIZED_CLIENT": "synthetic-agent-a",
            "A2A_AUTHORIZED_CLIENT": "synthetic-agent-a",
            "MCP_AUTHORIZED_CLIENT": "synthetic-agent-b",
            "JWKS_FILE_DIR": str(jwks_path.parent),
            "TOKEN_B_FILE": str(token_b_file),
            "TOKEN_C_FILE": str(token_c_file),
            "BANKING_SCOPE": "Banking.Read",
        }
    )

    run_status = None
    run_body = None
    agent_a_logs = ""
    agent_b_logs = ""
    gateway_logs = ""
    compose_ps = ""
    try:
        _compose_up_wait_build_if_needed(env, use_docker_compose=True)

        status, session, _ = _http_json(
            f"http://127.0.0.1:{api_port}/apps/agent_a/users/user-12345/sessions",
            method="POST",
            headers={
                "Authorization": f"Bearer {token_a}",
                "Content-Type": "application/json",
            },
            payload={},
        )
        assert status == 200, status
        session_id = session.get("id") if isinstance(session, dict) else None
        assert session_id

        run_payload = {
            "app_name": "agent_a",
            "user_id": "user-12345",
            "session_id": session_id,
            "new_message": {
                "role": "user",
                "parts": [{"text": "Delegate to Agent B and retrieve the balance for acct-1001. Use the approved read-only flow and keep the answer brief."}],
            },
        }
        try:
            status, events, headers = _http_json(
                f"http://127.0.0.1:{api_port}/run",
                method="POST",
                headers={
                    "Authorization": f"Bearer {token_a}",
                    "Content-Type": "application/json",
                    "X-Flow-ID": flow_id,
                },
                payload=run_payload,
            )
            run_status = status
            run_body = events
            assert status == 200, status
            response_flow_id = next((value for key, value in headers.items() if key.lower() == "x-flow-id"), None)
            assert response_flow_id == flow_id

            a2a_logs = _docker_compose(env, "logs", "--no-color", "agent-a", "agent-b", "banking-mcp", check=True).stdout
            assert flow_id in a2a_logs
            assert "a2a.message.sending" in a2a_logs
            assert "a2a.message.response_received" in a2a_logs
            assert "mcp_initialized" in a2a_logs
            assert "mcp_tools_discovered" in a2a_logs
            assert "mcp_tool_call_start" in a2a_logs
            assert "mcp_tool_call_complete" in a2a_logs
            assert "mcp_failure" not in a2a_logs
            assert "create_transfer" not in a2a_logs.lower()

            metrics = json.loads(
                _docker_exec(
                    env,
                    "banking-mcp",
                    "import json, urllib.request; print(json.dumps(json.loads(urllib.request.urlopen('http://127.0.0.1:8080/__debug/state', timeout=15).read().decode('utf-8'))))"
                )
            )
            assert metrics["tool_calls_total"] >= 1
            assert metrics["transfer_attempts_total"] == 0
            assert metrics["transfer_mutations_total"] == 0
            assert metrics["transfer_count"] == 0
            assert "create_transfer" not in json.dumps(metrics).lower()

            def _collect_structured_flow_events(log_text: str) -> list[str]:
                event_names: list[str] = []
                for line in log_text.splitlines():
                    if flow_id not in line:
                        continue
                    match = re.search(r'"event":"([^"]+)"', line)
                    if match:
                        event_names.append(match.group(1))
                return event_names

            def _is_tool_or_function_part(part: object) -> bool:
                if not isinstance(part, dict):
                    return False
                return any(
                    key in part
                    for key in (
                        "functionCall",
                        "functionResponse",
                        "function_call",
                        "function_response",
                        "toolCall",
                        "toolResponse",
                        "tool_call",
                        "tool_response",
                    )
                )

            def _extract_text_from_value(value: object) -> str:
                if isinstance(value, str):
                    return value.strip()
                if isinstance(value, list):
                    for item in value:
                        text = _extract_text_from_value(item)
                        if text:
                            return text
                    return ""
                if isinstance(value, dict):
                    for key in ("text", "result", "response", "content", "message"):
                        if key in value:
                            text = _extract_text_from_value(value.get(key))
                            if text:
                                return text
                    for item in value.values():
                        text = _extract_text_from_value(item)
                        if text:
                            return text
                return ""

            def _extract_ordinary_text_from_parts(parts: object) -> str:
                if not isinstance(parts, list):
                    return ""
                texts: list[str] = []
                for part in parts:
                    if _is_tool_or_function_part(part):
                        continue
                    if not isinstance(part, dict):
                        continue
                    if bool(part.get("thought")):
                        continue
                    part_type = str(part.get("type") or "").lower()
                    if part_type and "text" not in part_type:
                        continue
                    text = part.get("text")
                    if isinstance(text, str) and text.strip():
                        texts.append(text)
                return "\n".join(texts).strip()

            def _extract_function_response_text_from_parts(parts: object) -> str:
                if not isinstance(parts, list):
                    return ""
                for part in parts:
                    if not isinstance(part, dict):
                        continue
                    function_response = part.get("function_response") or part.get("functionResponse")
                    if not isinstance(function_response, dict):
                        continue
                    text = _extract_text_from_value(function_response.get("response"))
                    if text:
                        return text
                return ""

            def _extract_final_agent_a_response_text(run_events: object) -> str:
                if not isinstance(run_events, list):
                    return "<missing response text>"
                for event in reversed(run_events):
                    if not isinstance(event, dict):
                        continue
                    author = str(event.get("author") or "").lower()
                    if author != "agent_a":
                        continue
                    content = event.get("content")
                    parts = event.get("parts")
                    if isinstance(content, dict):
                        parts = content.get("parts")
                    ordinary_text = _extract_ordinary_text_from_parts(parts)
                    if ordinary_text:
                        sanitized = _sanitize_log_text(ordinary_text)
                        sanitized = re.sub(r"\b(?:acct|user)-\d+\b", "[redacted]", sanitized)
                        sanitized = re.sub(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", "[redacted]", sanitized)
                        return sanitized
                    for event in reversed(run_events):
                        if not isinstance(event, dict):
                            continue
                        content = event.get("content")
                        parts = event.get("parts")
                        if isinstance(content, dict):
                            parts = content.get("parts")
                        function_response_text = _extract_function_response_text_from_parts(parts)
                        if not function_response_text:
                            continue
                        sanitized = _sanitize_log_text(function_response_text)
                        sanitized = re.sub(r"\b(?:acct|user)-\d+\b", "[redacted]", sanitized)
                        sanitized = re.sub(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", "[redacted]", sanitized)
                        return sanitized
                return "<missing response text>"

            agent_a_flow_events = _collect_structured_flow_events(_docker_compose(env, "logs", "--no-color", "agent-a", check=True).stdout)
            agent_b_flow_events = _collect_structured_flow_events(_docker_compose(env, "logs", "--no-color", "agent-b", check=True).stdout)
            final_agent_a_response_text = _extract_final_agent_a_response_text(events)
            final_agent_a_response_text = re.sub(r"\b(?:acct|user)-\d+\b", "[redacted]", final_agent_a_response_text)
            final_agent_a_response_text = re.sub(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", "[redacted]", final_agent_a_response_text)
            final_agent_a_response_text = _sanitize_log_text(final_agent_a_response_text)
            diagnostic_snapshot = {
                "agent_a_delegated": "a2a.message.sending" in a2a_logs,
                "agent_b_called_mcp": all(event_name in a2a_logs for event_name in ["mcp_initialized", "mcp_tools_discovered", "mcp_tool_call_start", "mcp_tool_call_complete"]),
                "a2a_message_response_received": "a2a.message.response_received" in a2a_logs,
                "agent_a_flow_events": agent_a_flow_events,
                "agent_b_flow_events": agent_b_flow_events,
                "mcp_tool_call_start": "mcp_tool_call_start" in a2a_logs,
                "mcp_tool_call_complete": "mcp_tool_call_complete" in a2a_logs,
                "mcp_failure": "mcp_failure" in a2a_logs,
                "banking_mcp_counters": {
                    "tool_calls_total": metrics["tool_calls_total"],
                    "transfer_attempts_total": metrics["transfer_attempts_total"],
                    "transfer_mutations_total": metrics["transfer_mutations_total"],
                    "transfer_count": metrics["transfer_count"],
                },
                "final_agent_a_response_text": final_agent_a_response_text,
            }
            print("DIAGNOSTIC_SNAPSHOT", json.dumps(diagnostic_snapshot, sort_keys=True))
            normalized_final_response_text = final_agent_a_response_text.replace(",", "")
            assert "12345.67" in normalized_final_response_text

            token_b_claims = jwt.decode(token_b, options={"verify_signature": False})
            assert token_b_claims["aud"] == "api://agent-b-example"
            assert token_b_claims["scp"] == "AgentB.Access"
            assert token_b_claims["azp"] == "synthetic-agent-a"

            token_c_claims = jwt.decode(token_c, options={"verify_signature": False})
            assert token_c_claims["aud"] == "api://banking-mock"
            assert token_c_claims["scp"] == "Banking.Read"
            assert "Banking.Write" not in token_c_claims["scp"]

            assert "Banking.Read" in a2a_logs or "tool_calls_total" in json.dumps(metrics)
        except urllib.error.HTTPError as exc:
            run_status = exc.code
            run_body = exc.read().decode("utf-8", errors="replace")
            agent_a_logs = _sanitize_log_text(_docker_compose(env, "logs", "--no-color", "agent-a", check=True).stdout)
            agent_b_logs = _sanitize_log_text(_docker_compose(env, "logs", "--no-color", "agent-b", check=True).stdout)
            gateway_logs = _sanitize_log_text(_docker_compose(env, "logs", "--no-color", "agentgateway", check=True).stdout)
            compose_ps = _sanitize_log_text(_docker_compose(env, "ps", check=True).stdout)
            print(f"/run status: {run_status}")
            print(f"/run body: {run_body[:2000]}")
            print("--- agent-a logs ---")
            print(agent_a_logs[:4000])
            print("--- agent-b logs ---")
            print(agent_b_logs[:4000])
            print("--- agentgateway logs ---")
            print(gateway_logs[:4000])
            print("--- compose ps ---")
            print(compose_ps[:4000])
            raise
    finally:
        _docker_compose(env, "down", "-v", "--remove-orphans", check=False)
        remaining = subprocess.run(
            ["docker", "ps", "--filter", f"label=com.docker.compose.project={project_name}", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert remaining.stdout.strip() == ""


def test_unified_config_has_three_listeners_and_private_backends(tmp_path, monkeypatch):
    real_config = {
        "ENTRA_TENANT_ID": "tenant-live-123",
        "ENTRA_NOTEBOOK_CLIENT_ID": "notebook-client-live",
        "ENTRA_AGENT_A_CLIENT_ID": "agent-a-client-live",
        "ENTRA_AGENT_A_CLIENT_SECRET_FILE": "/tmp/live-agent-a-secret",
        "ENTRA_AGENT_A_SCOPE": "api://agent-a/AgentA.Access",
        "ENTRA_AGENT_A_EXPECTED_AUDIENCE": "api://agent-a-live",
        "ENTRA_AGENT_B_CLIENT_ID": "agent-b-client-live",
        "ENTRA_AGENT_B_SCOPE": "api://agent-b/AgentB.Access",
        "ENTRA_AGENT_B_EXPECTED_AUDIENCE": "api://agent-b-live",
        "ENTRA_AGENT_B_CLIENT_SECRET_FILE": "/tmp/live-agent-b-secret",
        "ENTRA_BANKING_SCOPES": "api://banking/Banking.Read api://banking/Banking.Write",
        "ENTRA_BANKING_EXPECTED_AUDIENCE": "api://banking-live",
    }
    runtime_env = live_unified_obo._compose_live_runtime_env(real_config)
    config_dir = tmp_path / "config"
    monkeypatch.setenv("AG_CONFIG_PATH", str(config_dir))
    for key, value in runtime_env.items():
        monkeypatch.setenv(key, value)
    config_path = Path(_load_renderer().render())
    rendered = config_path.read_text(encoding="utf-8")

    assert "api-edge:\n    port: 8080" in rendered
    assert "a2a:\n    port: 8081" in rendered
    assert "mcp:\n    port: 8082" in rendered
    assert 'jwks:\n        url: "https://login.microsoftonline.com/tenant-live-123/discovery/v2.0/keys"' in rendered
    assert 'mode: strict' in rendered
    assert 'mode: optional' in rendered
    assert "request.path == '/.well-known/agent-card.json'" in rendered
    assert 'jwt.tid ==' in rendered
    assert 'mcpAuthentication:' in rendered
    assert 'mcpAuthorization:' in rendered
    assert 'host: "agent-a:8000"' in rendered
    assert 'host: "agent-b:8001"' in rendered
    assert 'host: "http://banking-mcp:8080/mcp"' in rendered
    assert ' - "api://agent-b-live"' in rendered
    assert (
        '  - name: agent-a-api\n'
        '    gateways: [api-edge]\n'
        '    matches:\n'
        '      - path:\n'
        '          pathPrefix: /\n'
        '    backends:\n'
        '      - host: "agent-a:8000"\n'
        '        policies:\n'
        '          backendAuth:\n'
        '            passthrough: {}'
    ) in rendered
    assert (
        '  - name: agent-b-a2a\n'
        '    gateways: [a2a]\n'
        '    matches:\n'
        '      - path:\n'
        '          pathPrefix: /\n'
        '    backends:\n'
        '      - host: "agent-b:8001"\n'
        '        policies:\n'
        '          backendAuth:\n'
        '            passthrough: {}'
    ) in rendered
    assert "gateways: [api-edge]" in rendered
    assert "gateways: [a2a]" in rendered
    assert "gateways: [mcp]" in rendered


def test_unified_compose_publishes_only_gateway_ports(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    monkeypatch.setenv("AG_CONFIG_PATH", str(config_dir))
    _load_renderer().render()
    token_b_file = tmp_path / "token-b.txt"
    token_c_file = tmp_path / "token-c.txt"
    token_b_file.write_text("fixture-token-b\n", encoding="utf-8")
    token_c_file.write_text("fixture-token-c\n", encoding="utf-8")
    env = os.environ.copy()
    env.update(
        {
            "AG_CONFIG_PATH": str(config_dir),
            "API_HOST_PORT": str(_free_port()),
            "A2A_HOST_PORT": str(_free_port()),
            "MCP_HOST_PORT": str(_free_port()),
            "TOKEN_B_FILE": str(token_b_file),
            "TOKEN_C_FILE": str(token_c_file),
        }
    )
    result = _compose(env, "config")
    assert result.returncode == 0
    assert "jwks-fixture:" in result.stdout
    assert "agentgateway:" in result.stdout
    assert "agent-a:" in result.stdout
    assert "agent-b:" in result.stdout
    assert "banking-mcp:" in result.stdout
    assert result.stdout.count("published:") == 3


def test_unified_gateway_routes_all_three_listeners(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    monkeypatch.setenv("AG_CONFIG_PATH", str(config_dir))
    _load_renderer().render()
    api_port, a2a_port, mcp_port = _free_port(), _free_port(), _free_port()
    jwks_path, private_key = _write_public_jwks(tmp_path)
    assert jwks_path.exists()
    assert private_key is not None
    token_b_file = tmp_path / "token-b.txt"
    token_c_file = tmp_path / "token-c.txt"
    token_b_file.write_text("fixture-token-b\n", encoding="utf-8")
    token_c_file.write_text("fixture-token-c\n", encoding="utf-8")

    issuer = "https://login.microsoftonline.com/11111111-2222-3333-4444-555555666666/v2.0"
    token_a = _build_token_a(private_key, issuer)

    env = os.environ.copy()
    env.update(
        {
            "COMPOSE_PROJECT_NAME": f"solo-unified-{uuid.uuid4().hex[:8]}",
            "AG_CONFIG_PATH": str(config_dir),
            "API_HOST_PORT": str(api_port),
            "A2A_HOST_PORT": str(a2a_port),
            "MCP_HOST_PORT": str(mcp_port),
            "TENANT_ID": "11111111-2222-3333-4444-555555666666",
            "ISSUER": issuer,
            "API_AUDIENCE": "api://agent-a-example",
            "A2A_AUDIENCE": "api://agent-b-example",
            "MCP_AUDIENCE": "api://banking-mock",
            "API_AUTHORIZED_CLIENT": "synthetic-agent-a",
            "A2A_AUTHORIZED_CLIENT": "synthetic-agent-a",
            "MCP_AUTHORIZED_CLIENT": "synthetic-agent-b",
            "JWKS_FILE_DIR": str(jwks_path.parent),
            "TOKEN_B_FILE": str(token_b_file),
            "TOKEN_C_FILE": str(token_c_file),
        }
    )
    try:
        _compose_up_wait_build_if_needed(env, use_docker_compose=False)
        assert b"ok" in _wait(
            f"http://127.0.0.1:{api_port}/health",
            headers={"Authorization": f"Bearer {token_a}"},
        ).lower()
        card = _wait(f"http://127.0.0.1:{a2a_port}/.well-known/agent-card.json")
        assert b"agent_b" in card.lower()
        assert b"http://agentgateway:8081/" in card.lower()
        assert b"127.0.0.1" not in card.lower()
        assert b"mock-banking" in _wait(
            f"http://127.0.0.1:{mcp_port}/healthz"
        ).lower()
    finally:
        _compose(env, "down", "-v", "--remove-orphans", check=False)


def test_unified_a2a_gateway_forwards_token_b_to_agent_b(tmp_path, monkeypatch):
    _require_ollama_model("qwen3:8b")

    config_dir = tmp_path / "config"
    monkeypatch.setenv("AG_CONFIG_PATH", str(config_dir))
    _load_renderer().render()

    jwks_path, private_key = _write_public_jwks(tmp_path)
    token_b_file = tmp_path / "token-b.txt"
    token_c_file = tmp_path / "token-c.txt"

    issuer = "https://login.microsoftonline.com/11111111-2222-3333-4444-555555666666/v2.0"
    token_b = _build_token_for_scope(
        private_key,
        issuer,
        audience="api://agent-b-example",
        scope="AgentB.Access",
        authorized_client="synthetic-agent-a",
    )
    token_c = _build_token_for_scope(
        private_key,
        issuer,
        audience="api://banking-mock",
        scope="Banking.Read",
        authorized_client="synthetic-agent-b",
    )
    token_b_file.write_text(token_b, encoding="utf-8")
    token_c_file.write_text(token_c, encoding="utf-8")

    flow_id = "a2a-token-b-forward-123"
    api_port = _free_port()
    a2a_port = _free_port()
    mcp_port = _free_port()
    project_name = f"solo-a2a-forward-{uuid.uuid4().hex[:8]}"

    env = os.environ.copy()
    env.update(
        {
            "COMPOSE_PROJECT_NAME": project_name,
            "AG_CONFIG_PATH": str(config_dir),
            "API_HOST_PORT": str(api_port),
            "A2A_HOST_PORT": str(a2a_port),
            "MCP_HOST_PORT": str(mcp_port),
            "TENANT_ID": "11111111-2222-3333-4444-555555666666",
            "ISSUER": issuer,
            "API_AUDIENCE": "api://agent-a-example",
            "A2A_AUDIENCE": "api://agent-b-example",
            "MCP_AUDIENCE": "api://banking-mock",
            "API_AUTHORIZED_CLIENT": "synthetic-agent-a",
            "A2A_AUTHORIZED_CLIENT": "synthetic-agent-a",
            "MCP_AUTHORIZED_CLIENT": "synthetic-agent-b",
            "JWKS_FILE_DIR": str(jwks_path.parent),
            "TOKEN_B_FILE": str(token_b_file),
            "TOKEN_C_FILE": str(token_c_file),
            "BANKING_SCOPE": "Banking.Read",
            "AGENT_B_TOKEN_C_MODE": "file",
        }
    )

    valid_message_payload = {
        "jsonrpc": "2.0",
        "method": "message/send",
        "params": {
            "message": {
                "messageId": "forward-check",
                "role": "user",
                "parts": [{"kind": "text", "text": "hello from agent a"}],
            }
        },
        "id": "forward-check",
    }
    unauthenticated_payload = {
        "jsonrpc": "2.0",
        "method": "message/send",
        "params": {
            "message": {
                "messageId": "forward-check-unauth",
                "role": "user",
                "parts": [{"kind": "text", "text": "hello from agent a"}],
            }
        },
        "id": "forward-check-unauth",
    }

    try:
        _compose_up_wait_build_if_needed(env, use_docker_compose=True)

        status, agent_card, _ = _http_json(f"http://127.0.0.1:{a2a_port}/.well-known/agent-card.json")
        assert status == 200
        assert isinstance(agent_card, dict)
        assert agent_card.get("name") == "agent_b"

        advertised_url = agent_card.get("url")
        if not isinstance(advertised_url, str) or not advertised_url.strip():
            for field_name in ("supportedInterfaces", "supported_interfaces"):
                interfaces = agent_card.get(field_name)
                if not isinstance(interfaces, list):
                    continue
                for interface in interfaces:
                    if not isinstance(interface, dict):
                        continue
                    advertised_url = interface.get("url") or interface.get("rpc_url") or interface.get("uri")
                    if isinstance(advertised_url, str) and advertised_url.strip():
                        break
                if isinstance(advertised_url, str) and advertised_url.strip():
                    break

        assert isinstance(advertised_url, str) and advertised_url.strip(), "Agent Card did not advertise a protected interface URL"
        advertised_path = urlparse(advertised_url).path or "/"
        assert advertised_path == "/"
        protected_url = f"http://127.0.0.1:{a2a_port}{advertised_path}"

        status, body, _ = _http_json(
            protected_url,
            method="POST",
            headers={
                "Authorization": f"Bearer {token_b}",
                "Content-Type": "application/json",
                "X-Flow-ID": flow_id,
            },
            payload=valid_message_payload,
        )
        assert status == 200
        assert isinstance(body, dict)
        assert body.get("jsonrpc") == "2.0"
        assert "error" not in body

        with pytest.raises(urllib.error.HTTPError) as exc_info:
            _http_json(
                protected_url,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "X-Flow-ID": f"{flow_id}-unauth",
                },
                payload=unauthenticated_payload,
            )

        assert exc_info.value.code in {401, 403}
        unauthenticated_body_text = exc_info.value.read().decode("utf-8", errors="replace")
        assert unauthenticated_body_text.strip().lower() == "authorization failed"

        agent_b_logs = _docker_compose(env, "logs", "--no-color", "agent-b", check=True).stdout
        gateway_logs = _docker_compose(env, "logs", "--no-color", "agentgateway", check=True).stdout
        delegated_event_marker = '"delegated_token_present":true'

        assert flow_id in agent_b_logs
        assert "agent_b.delegated_token.received" in agent_b_logs
        assert delegated_event_marker in agent_b_logs
        assert f"{flow_id}-unauth" not in agent_b_logs
        assert "agent_b.delegated_token.received" not in gateway_logs
        assert delegated_event_marker not in gateway_logs
        assert "eyJ" not in agent_b_logs
        assert "Bearer " not in agent_b_logs
        assert "synthetic-agent-a" not in agent_b_logs
        assert "user-12345" not in agent_b_logs
        assert "eyJ" not in gateway_logs
        assert "Bearer " not in gateway_logs
    finally:
        _compose(env, "down", "-v", "--remove-orphans", check=False)
        remaining = subprocess.run(
            ["docker", "ps", "--filter", f"label=com.docker.compose.project={project_name}", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert remaining.stdout.strip() == ""


def test_live_unified_mcp_summary_handles_sse_initialize_tools_and_call(monkeypatch):
    def _sse_payload(payload: dict[str, object]) -> str:
        return f"data: {json.dumps(payload)}\n\n"

    class FakeResponse:
        def __init__(self, *, headers: dict[str, str] | None = None, status_code: int = 200, text: str = ""):
            self.headers = headers or {}
            self.status_code = status_code
            self.text = text

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}: {self.text}")

    class FakeAsyncClient:
        def __init__(self):
            self.calls: list[dict[str, object]] = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, *, json=None, headers=None):
            self.calls.append({"url": url, "json": json, "headers": dict(headers or {})})
            if json["method"] == "initialize":
                return FakeResponse(headers={"Mcp-Session-Id": "sess-live"}, text=_sse_payload({
                    "jsonrpc": "2.0",
                    "result": {
                        "protocolVersion": "2025-03-26",
                        "capabilities": {},
                        "serverInfo": {"name": "banking-mcp", "version": "1.0.0"},
                    },
                }))
            if json["method"] == "notifications/initialized":
                return FakeResponse(status_code=202, text="")
            if json["method"] == "tools/list":
                return FakeResponse(text=_sse_payload({
                    "jsonrpc": "2.0",
                    "result": {"tools": [{"name": "get_account_summary", "description": "Read a balance"}]},
                }))
            if json["method"] == "tools/call":
                return FakeResponse(text=_sse_payload({
                    "jsonrpc": "2.0",
                    "result": {"content": [{"type": "text", "text": "Balance for acct-1001 is 12345.67"}]},
                }))
            raise AssertionError(f"Unexpected MCP method: {json['method']}")

    fake_client = FakeAsyncClient()
    monkeypatch.setattr("httpx.AsyncClient", lambda *args, **kwargs: fake_client)

    result = live_unified_obo._call_mcp_summary("http://example.test/mcp", "token-c-live", "acct-1001")

    assert result == "Balance for acct-1001 is 12345.67"
    assert [call["json"]["method"] for call in fake_client.calls] == [
        "initialize",
        "notifications/initialized",
        "tools/list",
        "tools/call",
    ]
    assert fake_client.calls[0]["headers"]["Authorization"] == "Bearer token-c-live"
    assert fake_client.calls[0]["headers"]["Accept"] == "application/json, text/event-stream"
    assert fake_client.calls[3]["headers"]["Mcp-Session-Id"] == "sess-live"
