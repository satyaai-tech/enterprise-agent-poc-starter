from __future__ import annotations

import base64
import json
import os
import socket
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

REPO_ROOT = Path(__file__).resolve().parents[2]
SPIKE_DIR = REPO_ROOT / "experiments" / "solo-agentgateway" / "mcp"
COMPOSE_FILE = SPIKE_DIR / "compose.yaml"
MCP_SESSION_IDS: dict[str, str | None] = {}


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def unique_compose_env(*, host_port: int | None = None, project_name: str | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env["COMPOSE_PROJECT_NAME"] = project_name or f"solo-mcp-{uuid.uuid4().hex[:8]}"
    env["HOST_PORT"] = str(host_port or get_free_port())
    return env


def run_compose(*args: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), *args],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )


def wait_for_http(url: str, *, timeout: float = 120.0) -> dict[str, object]:
    deadline = time.time() + timeout
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            with urlopen(url, timeout=2) as response:
                body = response.read().decode("utf-8")
                return {"status": response.status, "body": body}
        except HTTPError as error:
            if error.code in {401, 403}:
                return {"status": error.code, "body": error.read().decode("utf-8")}
            last_error = error
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        time.sleep(1)
    raise RuntimeError(f"Timed out waiting for {url}: {last_error}")


def _parse_mcp_payload(raw: str) -> dict[str, object]:
    text = raw.strip()
    if not text:
        return {"jsonrpc": "2.0", "error": {"code": -32001, "message": "empty response"}}
    if "data:" in text:
        candidates = [line[len("data:") :].strip() for line in text.splitlines() if line.strip().startswith("data:")]
        for candidate in reversed(candidates):
            if not candidate or candidate == "[DONE]":
                continue
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"jsonrpc": "2.0", "error": {"code": -32001, "message": text}}


def initialize_mcp_session(url: str, *, token: str | None = None) -> str | None:
    init_payload = {
        "jsonrpc": "2.0",
        "id": "init-session",
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "synthetic-client", "version": "1.0.0"},
        },
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": "2025-03-26",
        "X-Correlation-Id": "mcp-init",
    }
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, headers=headers, method="POST", data=json.dumps(init_payload).encode("utf-8"))
    try:
        with urlopen(request, timeout=10) as response:
            body = response.read().decode("utf-8")
            response_payload = _parse_mcp_payload(body)
            session_id = response.headers.get("Mcp-Session-Id") or response.headers.get("mcp-session-id")
            if session_id:
                MCP_SESSION_IDS[url] = session_id
                notification_headers = {
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                    "MCP-Protocol-Version": "2025-03-26",
                    "Mcp-Session-Id": session_id,
                    "X-Correlation-Id": "mcp-notify",
                }
                if token is not None:
                    notification_headers["Authorization"] = f"Bearer {token}"
                notification_payload = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
                notification_request = Request(
                    url,
                    headers=notification_headers,
                    method="POST",
                    data=json.dumps(notification_payload).encode("utf-8"),
                )
                try:
                    with urlopen(notification_request, timeout=10) as notification_response:
                        notification_response.read()
                except HTTPError:
                    pass
                return session_id
            return response_payload.get("result") is not None and session_id
    except HTTPError as error:
        error.read()
        return None
    except URLError as error:
        raise RuntimeError(f"MCP initialize request failed: {error}") from error


def request_json(
    url: str,
    *,
    token: str | None = None,
    method: str = "POST",
    payload: dict[str, object] | None = None,
    correlation_id: str = "corr-mcp-test",
    extra_headers: dict[str, str] | None = None,
    session_id: str | None = None,
) -> tuple[int, dict[str, object]]:
    if payload is not None and payload.get("method") in {"tools/list", "tools/call"} and session_id is None:
        session_id = MCP_SESSION_IDS.get(url) or initialize_mcp_session(url, token=token)
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": "2025-03-26",
        "X-Correlation-Id": correlation_id,
    }
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    if extra_headers:
        headers.update(extra_headers)
    request = Request(
        url,
        headers=headers,
        method=method,
        data=None if payload is None else json.dumps(payload).encode("utf-8"),
    )
    try:
        with urlopen(request, timeout=10) as response:
            body = response.read().decode("utf-8")
            return response.status, _parse_mcp_payload(body)
    except HTTPError as error:
        text = error.read().decode("utf-8")
        parsed = _parse_mcp_payload(text)
        if parsed.get("error") is None and text:
            parsed = {"jsonrpc": "2.0", "error": {"code": error.code, "message": text}}
        return error.code, parsed
    except URLError as error:
        raise RuntimeError(f"Request failed: {error}") from error


def rsa_key_pair() -> tuple[object, dict[str, object]]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(public_key))
    public_jwk["kid"] = "synthetic-kid"
    return private_key, public_jwk


def build_token(
    private_key,
    *,
    tenant_id: str,
    audience: str,
    scope: str,
    issuer: str,
    authorized_client: str,
    subject: str,
    version: str = "2.0",
    expired: bool = False,
    expiration_offset: int | None = None,
    not_yet_valid: bool = False,
    include_iat: bool = True,
    algorithm: str = "RS256",
    signing_secret: str | None = None,
    overrides: dict[str, object] | None = None,
) -> str:
    now = int(datetime.now(timezone.utc).timestamp())
    payload: dict[str, object] = {
        "iss": issuer,
        "aud": audience,
        "tid": tenant_id,
        "scp": scope,
        "sub": subject,
        "oid": subject,
        "iat": now - 120,
        "nbf": now - 60,
        "exp": now + 3600,
        "ver": version,
    }
    if version == "2.0":
        payload["azp"] = authorized_client
    else:
        payload["appid"] = authorized_client
    if expiration_offset is not None:
        payload["exp"] = now + expiration_offset
    elif expired:
        payload["exp"] = now - 30
    if not_yet_valid:
        payload["nbf"] = now + 300
    if not include_iat:
        payload.pop("iat", None)
    if overrides:
        payload.update(overrides)

    signing_key = private_key if signing_secret is None else signing_secret
    return jwt.encode(payload, signing_key, algorithm=algorithm, headers={"kid": "synthetic-kid"})


def tamper_signature(token: str) -> str:
    header, payload, signature = token.split(".")
    padded = signature + ("=" * (-len(signature) % 4))
    decoded = base64.urlsafe_b64decode(padded.encode("ascii"))
    tampered = bytearray(decoded)
    tampered[0] ^= 0x01
    encoded = base64.urlsafe_b64encode(bytes(tampered)).rstrip(b"=").decode("ascii")
    return f"{header}.{payload}.{encoded}"


def read_backend_debug_state(env: dict[str, str]) -> dict[str, object]:
    command = (
        "import json, urllib.request; "
        "payload = urllib.request.urlopen('http://localhost:8080/__debug/state', timeout=5).read().decode('utf-8'); "
        "print(payload)"
    )
    result = subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "exec", "-T", "mock-banking", "python", "-c", command],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(result.stdout)


def reset_backend_debug_state(env: dict[str, str]) -> None:
    command = "import urllib.request; urllib.request.urlopen('http://localhost:8080/__debug/reset', timeout=5).read()"
    subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "exec", "-T", "mock-banking", "python", "-c", command],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )


def unique_idempotency_key(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def render_config(*, tmp_dir: Path, tenant_id: str, issuer: str, audience: str, scope: str, authorized_client: str, host_port: int | str | None = None) -> tuple[Path, Path, Path, object]:
    fixture_dir = tmp_dir / "fixtures"
    fixture_dir.mkdir(parents=True, exist_ok=True)
    private_key, public_jwk = rsa_key_pair()
    jwks_path = fixture_dir / "jwks.json"
    jwks_path.write_text(json.dumps({"keys": [public_jwk]}, indent=2), encoding="utf-8")

    config_path = tmp_dir / "agentgateway-config.yaml"
    env = unique_compose_env(host_port=host_port or get_free_port())
    if host_port is not None:
        env["GATEWAY_RESOURCE"] = f"http://localhost:{host_port}/mcp"
    env.update(
        {
            "TENANT_ID": tenant_id,
            "ISSUER": issuer,
            "EXPECTED_AUDIENCE": audience,
            "EXPECTED_SCOPE": scope,
            "AUTHORIZED_CLIENT": authorized_client,
            "AG_CONFIG_PATH": str(config_path),
            "JWKS_FILE_DIR": str(fixture_dir),
        }
    )
    subprocess.run(["python3", str(SPIKE_DIR / "render_config.py")], cwd=REPO_ROOT, env=env, check=True)
    return jwks_path, config_path, fixture_dir, private_key


@pytest.fixture(scope="module")
def mcp_stack(tmp_path_factory: pytest.TempPathFactory):
    tenant_id = "11111111-2222-3333-4444-555555666666"
    issuer = f"https://login.microsoftonline.com/{tenant_id}/v2.0"
    audience = "api://banking-mock"
    scope = "Banking.Read Banking.Write"
    authorized_client = "synthetic-agent-b"
    subject = "user-12345"

    tmp_dir = tmp_path_factory.mktemp("mcp-stack")
    gateway_port = get_free_port()
    jwks_path, config_path, fixture_dir, private_key = render_config(
        tmp_dir=tmp_dir,
        tenant_id=tenant_id,
        issuer=issuer,
        audience=audience,
        scope=scope,
        authorized_client=authorized_client,
        host_port=gateway_port,
    )
    env = unique_compose_env(host_port=gateway_port)
    env.update(
        {
            "TENANT_ID": tenant_id,
            "ISSUER": issuer,
            "EXPECTED_AUDIENCE": audience,
            "EXPECTED_SCOPE": scope,
            "AUTHORIZED_CLIENT": authorized_client,
            "AG_CONFIG_PATH": str(config_path),
            "JWKS_FILE_DIR": str(jwks_path.parent),
        }
    )
    gateway_url = f"http://localhost:{gateway_port}/"

    try:
        run_compose("up", "-d", "--build", env=env)
        wait_for_http(f"{gateway_url}healthz")
        yield {
            "env": env,
            "gateway_url": gateway_url,
            "tenant_id": tenant_id,
            "issuer": issuer,
            "audience": audience,
            "scope": scope,
            "authorized_client": authorized_client,
            "subject": subject,
            "private_key": private_key,
            "jwks_path": jwks_path,
        }
    finally:
        result = subprocess.run(
            ["docker", "compose", "-f", str(COMPOSE_FILE), "down", "-v", "--remove-orphans"],
            cwd=REPO_ROOT,
            env=env,
            text=True,
            capture_output=True,
        )
        if result.returncode != 0 and "No such container" not in result.stderr:
            raise RuntimeError(f"docker compose down failed: {result.stderr or result.stdout}")


@pytest.fixture(autouse=True)
def reset_mcp_state(mcp_stack: dict[str, object]):
    reset_backend_debug_state(mcp_stack["env"])
    yield
    reset_backend_debug_state(mcp_stack["env"])


def test_compose_config_validation(tmp_path: Path):
    tenant_id = "11111111-2222-3333-4444-555555666666"
    issuer = f"https://login.microsoftonline.com/{tenant_id}/v2.0"
    audience = "api://banking-mock"
    authorized_client = "synthetic-agent-b"
    jwks_path, config_path, _, _ = render_config(
        tmp_dir=tmp_path,
        tenant_id=tenant_id,
        issuer=issuer,
        audience=audience,
        scope="Banking.Read Banking.Write",
        authorized_client=authorized_client,
    )
    env = unique_compose_env(host_port=get_free_port())
    env.update({
        "TENANT_ID": tenant_id,
        "ISSUER": issuer,
        "EXPECTED_AUDIENCE": audience,
        "EXPECTED_SCOPE": "Banking.Read Banking.Write",
        "AUTHORIZED_CLIENT": authorized_client,
        "AG_CONFIG_PATH": str(config_path),
        "JWKS_FILE_DIR": str(jwks_path.parent),
    })
    run_compose("config", env=env)


def test_solo_agentgateway_mcp_valid_tool_call(mcp_stack: dict[str, object]):
    gateway_url = mcp_stack["gateway_url"]
    token = build_token(
        mcp_stack["private_key"],
        tenant_id=mcp_stack["tenant_id"],
        audience=mcp_stack["audience"],
        scope=mcp_stack["scope"],
        issuer=mcp_stack["issuer"],
        authorized_client=mcp_stack["authorized_client"],
        subject=mcp_stack["subject"],
    )

    payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": "get_account_summary", "arguments": {"account_id": "acct-1001"}},
        "id": "read-tool-check",
    }
    status, body = request_json(f"{gateway_url}mcp", token=token, payload=payload)
    assert status == 200
    assert body["jsonrpc"] == "2.0"
    assert body["result"]["content"][0]["text"] == "Balance for acct-1001 is 12345.67"


def test_solo_agentgateway_mcp_scopes_filter_tool_discovery_and_direct_calls(mcp_stack: dict[str, object]):
    gateway_url = mcp_stack["gateway_url"]
    read_only_token = build_token(
        mcp_stack["private_key"],
        tenant_id=mcp_stack["tenant_id"],
        audience=mcp_stack["audience"],
        scope="Banking.Read",
        issuer=mcp_stack["issuer"],
        authorized_client=mcp_stack["authorized_client"],
        subject=mcp_stack["subject"],
    )

    list_status, list_body = request_json(
        f"{gateway_url}mcp",
        token=read_only_token,
        payload={"jsonrpc": "2.0", "method": "tools/list", "params": {}, "id": "read-list"},
    )
    assert list_status == 200
    tool_names = [tool["name"] for tool in list_body["result"]["tools"]]
    assert tool_names == ["get_account_summary"]

    before = read_backend_debug_state(mcp_stack["env"])
    write_payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": "create_transfer", "arguments": {"from_account": "acct-1001", "to_account": "acct-2002", "amount": 25.0, "confirmation": "yes"}},
        "id": "read-write-blocked",
    }
    status, body = request_json(f"{gateway_url}mcp", token=read_only_token, payload=write_payload)
    after = read_backend_debug_state(mcp_stack["env"])

    assert status == 400
    assert body["jsonrpc"] == "2.0"
    assert body["error"]["code"] == -32602
    assert "Unknown tool" in body["error"]["message"]
    assert "create_transfer" not in [tool["name"] for tool in list_body["result"]["tools"]]
    assert "get_account_summary" in [tool["name"] for tool in list_body["result"]["tools"]]
    assert after["tool_calls_total"] == before["tool_calls_total"]
    assert after["transfer_attempts_total"] == before["transfer_attempts_total"]
    assert after["transfer_mutations_total"] == before["transfer_mutations_total"]


def test_solo_agentgateway_mcp_write_requires_write_scope(mcp_stack: dict[str, object]):
    gateway_url = mcp_stack["gateway_url"]
    read_only_token = build_token(
        mcp_stack["private_key"],
        tenant_id=mcp_stack["tenant_id"],
        audience=mcp_stack["audience"],
        scope="Banking.Read",
        issuer=mcp_stack["issuer"],
        authorized_client=mcp_stack["authorized_client"],
        subject=mcp_stack["subject"],
    )
    before = read_backend_debug_state(mcp_stack["env"])
    payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": "create_transfer", "arguments": {"from_account": "acct-1001", "to_account": "acct-2002", "amount": 25.0, "confirmation": "yes"}},
        "id": "write-tool-check",
    }
    status, body = request_json(f"{gateway_url}mcp", token=read_only_token, payload=payload, extra_headers={"X-Idempotency-Key": "write-scope-1"})
    after = read_backend_debug_state(mcp_stack["env"])
    assert status == 400
    assert body["error"]["code"] == -32602
    assert "Unknown tool" in body["error"]["message"]
    assert after["tool_calls_total"] == before["tool_calls_total"]
    assert after["transfer_attempts_total"] == before["transfer_attempts_total"]
    assert after["transfer_mutations_total"] == before["transfer_mutations_total"]


def test_solo_agentgateway_mcp_rejects_wrong_account_owner(mcp_stack: dict[str, object]):
    gateway_url = mcp_stack["gateway_url"]
    before = read_backend_debug_state(mcp_stack["env"])
    token = build_token(
        mcp_stack["private_key"],
        tenant_id=mcp_stack["tenant_id"],
        audience=mcp_stack["audience"],
        scope=mcp_stack["scope"],
        issuer=mcp_stack["issuer"],
        authorized_client=mcp_stack["authorized_client"],
        subject=mcp_stack["subject"],
    )
    payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": "get_account_summary", "arguments": {"account_id": "acct-9000"}},
        "id": "wrong-owner-check",
    }
    status, body = request_json(f"{gateway_url}mcp", token=token, payload=payload)
    after = read_backend_debug_state(mcp_stack["env"])
    assert status == 403
    assert body["error"]["code"] == -32007
    assert "Account not authorized for this user" in body["error"]["message"]
    assert after["tool_calls_total"] == before["tool_calls_total"] + 1
    assert after["rejected_total"] == before["rejected_total"] + 1
    assert after["transfer_mutations_total"] == before["transfer_mutations_total"]


def test_solo_agentgateway_mcp_rejects_missing_confirmation_without_mutation(mcp_stack: dict[str, object]):
    gateway_url = mcp_stack["gateway_url"]
    before = read_backend_debug_state(mcp_stack["env"])
    token = build_token(
        mcp_stack["private_key"],
        tenant_id=mcp_stack["tenant_id"],
        audience=mcp_stack["audience"],
        scope=mcp_stack["scope"],
        issuer=mcp_stack["issuer"],
        authorized_client=mcp_stack["authorized_client"],
        subject=mcp_stack["subject"],
    )
    payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": "create_transfer", "arguments": {"from_account": "acct-1001", "to_account": "acct-2002", "amount": 25.0}},
        "id": "missing-confirmation-check",
    }
    status, body = request_json(f"{gateway_url}mcp", token=token, payload=payload, extra_headers={"X-Idempotency-Key": "missing-confirmation-1"})
    assert status in {400, 403}
    assert body["jsonrpc"] == "2.0"
    assert "error" in body
    after = read_backend_debug_state(mcp_stack["env"])
    assert after["transfer_mutations_total"] == before["transfer_mutations_total"]


def test_solo_agentgateway_mcp_rejects_zero_amount_without_mutation(mcp_stack: dict[str, object]):
    gateway_url = mcp_stack["gateway_url"]
    before = read_backend_debug_state(mcp_stack["env"])
    token = build_token(
        mcp_stack["private_key"],
        tenant_id=mcp_stack["tenant_id"],
        audience=mcp_stack["audience"],
        scope=mcp_stack["scope"],
        issuer=mcp_stack["issuer"],
        authorized_client=mcp_stack["authorized_client"],
        subject=mcp_stack["subject"],
    )
    payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": "create_transfer", "arguments": {"from_account": "acct-1001", "to_account": "acct-2002", "amount": 0.0, "confirmation": "yes"}},
        "id": "zero-amount-check",
    }
    status, body = request_json(f"{gateway_url}mcp", token=token, payload=payload, extra_headers={"X-Idempotency-Key": "zero-amount-1"})
    assert status in {400, 403}
    assert body["jsonrpc"] == "2.0"
    assert "error" in body
    after = read_backend_debug_state(mcp_stack["env"])
    assert after["transfer_mutations_total"] == before["transfer_mutations_total"]


def test_solo_agentgateway_mcp_rejects_negative_amount_without_mutation(mcp_stack: dict[str, object]):
    gateway_url = mcp_stack["gateway_url"]
    before = read_backend_debug_state(mcp_stack["env"])
    token = build_token(
        mcp_stack["private_key"],
        tenant_id=mcp_stack["tenant_id"],
        audience=mcp_stack["audience"],
        scope=mcp_stack["scope"],
        issuer=mcp_stack["issuer"],
        authorized_client=mcp_stack["authorized_client"],
        subject=mcp_stack["subject"],
    )
    payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": "create_transfer", "arguments": {"from_account": "acct-1001", "to_account": "acct-2002", "amount": -5.0, "confirmation": "yes"}},
        "id": "negative-amount-check",
    }
    status, body = request_json(f"{gateway_url}mcp", token=token, payload=payload, extra_headers={"X-Idempotency-Key": "negative-amount-1"})
    assert status in {400, 403}
    assert body["jsonrpc"] == "2.0"
    assert "error" in body
    after = read_backend_debug_state(mcp_stack["env"])
    assert after["transfer_mutations_total"] == before["transfer_mutations_total"]


def test_solo_agentgateway_mcp_rejects_missing_idempotency_key_without_mutation(mcp_stack: dict[str, object]):
    gateway_url = mcp_stack["gateway_url"]
    before = read_backend_debug_state(mcp_stack["env"])
    token = build_token(
        mcp_stack["private_key"],
        tenant_id=mcp_stack["tenant_id"],
        audience=mcp_stack["audience"],
        scope=mcp_stack["scope"],
        issuer=mcp_stack["issuer"],
        authorized_client=mcp_stack["authorized_client"],
        subject=mcp_stack["subject"],
    )
    payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": "create_transfer", "arguments": {"from_account": "acct-1001", "to_account": "acct-2002", "amount": 10.0, "confirmation": "yes"}},
        "id": "missing-idempotency-check",
    }
    status, body = request_json(f"{gateway_url}mcp", token=token, payload=payload)
    assert status in {400, 401, 403}
    assert body["jsonrpc"] == "2.0"
    assert "error" in body
    after = read_backend_debug_state(mcp_stack["env"])
    assert after["transfer_mutations_total"] == before["transfer_mutations_total"]


def test_solo_agentgateway_mcp_replay_uses_one_mutation_only(mcp_stack: dict[str, object]):
    gateway_url = mcp_stack["gateway_url"]
    before = read_backend_debug_state(mcp_stack["env"])
    token = build_token(
        mcp_stack["private_key"],
        tenant_id=mcp_stack["tenant_id"],
        audience=mcp_stack["audience"],
        scope=mcp_stack["scope"],
        issuer=mcp_stack["issuer"],
        authorized_client=mcp_stack["authorized_client"],
        subject=mcp_stack["subject"],
    )
    payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": "create_transfer", "arguments": {"from_account": "acct-1001", "to_account": "acct-2002", "amount": 25.0, "confirmation": "yes"}},
        "id": "idempotent-retry-check",
    }
    first_status, first_body = request_json(f"{gateway_url}mcp", token=token, payload=payload, extra_headers={"X-Idempotency-Key": "single-mutation-1"})
    second_status, second_body = request_json(f"{gateway_url}mcp", token=token, payload=payload, extra_headers={"X-Idempotency-Key": "single-mutation-1"})
    assert first_status == 200
    assert second_status == 200
    assert first_body["result"]["structuredContent"]["transfer_id"] == second_body["result"]["structuredContent"]["transfer_id"]
    after = read_backend_debug_state(mcp_stack["env"])
    assert after["transfer_mutations_total"] == before["transfer_mutations_total"] + 1
    assert after["idempotent_retries_total"] == before["idempotent_retries_total"] + 1


def test_solo_agentgateway_mcp_conflicting_idempotency_key_does_not_mutate_again(mcp_stack: dict[str, object]):
    gateway_url = mcp_stack["gateway_url"]
    before = read_backend_debug_state(mcp_stack["env"])
    token = build_token(
        mcp_stack["private_key"],
        tenant_id=mcp_stack["tenant_id"],
        audience=mcp_stack["audience"],
        scope=mcp_stack["scope"],
        issuer=mcp_stack["issuer"],
        authorized_client=mcp_stack["authorized_client"],
        subject=mcp_stack["subject"],
    )
    first_payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": "create_transfer", "arguments": {"from_account": "acct-1001", "to_account": "acct-2002", "amount": 25.0, "confirmation": "yes"}},
        "id": "conflict-idempotency-first",
    }
    status_one, _ = request_json(f"{gateway_url}mcp", token=token, payload=first_payload, extra_headers={"X-Idempotency-Key": "conflicting-key-1"})
    assert status_one == 200
    second_payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": "create_transfer", "arguments": {"from_account": "acct-1001", "to_account": "acct-2002", "amount": 42.0, "confirmation": "yes"}},
        "id": "conflict-idempotency-second",
    }
    conflict_status, conflict_body = request_json(f"{gateway_url}mcp", token=token, payload=second_payload, extra_headers={"X-Idempotency-Key": "conflicting-key-1"})
    assert conflict_status in {400, 409}
    assert conflict_body["jsonrpc"] == "2.0"
    assert "error" in conflict_body
    after = read_backend_debug_state(mcp_stack["env"])
    assert after["transfer_mutations_total"] == before["transfer_mutations_total"] + 1


def test_solo_agentgateway_mcp_rejects_agent_b_audience_before_backend_tool_handling(mcp_stack: dict[str, object]):
    gateway_url = mcp_stack["gateway_url"]
    before = read_backend_debug_state(mcp_stack["env"])
    token = build_token(
        mcp_stack["private_key"],
        tenant_id=mcp_stack["tenant_id"],
        audience="api://agent-b",
        scope=mcp_stack["scope"],
        issuer=mcp_stack["issuer"],
        authorized_client=mcp_stack["authorized_client"],
        subject=mcp_stack["subject"],
    )
    payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": "get_account_summary", "arguments": {"account_id": "acct-1001"}},
        "id": "token-b-audience-check",
    }
    status, body = request_json(f"{gateway_url}mcp", token=token, payload=payload)
    after = read_backend_debug_state(mcp_stack["env"])
    assert status == 401
    assert "error" in body
    assert "jsonrpc" not in body
    assert "api://banking-mock" not in json.dumps(body, sort_keys=True)
    assert after["tool_calls_total"] == before["tool_calls_total"]


def test_solo_agentgateway_mcp_rejects_wrong_agent_b_identity_before_backend_tool_handling(mcp_stack: dict[str, object]):
    gateway_url = mcp_stack["gateway_url"]
    before = read_backend_debug_state(mcp_stack["env"])
    payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": "get_account_summary", "arguments": {"account_id": "acct-1001"}},
        "id": "wrong-agent-b-client-check",
    }
    wrong_client_token = build_token(
        mcp_stack["private_key"],
        tenant_id=mcp_stack["tenant_id"],
        audience=mcp_stack["audience"],
        scope=mcp_stack["scope"],
        issuer=mcp_stack["issuer"],
        authorized_client="synthetic-agent-c",
        subject=mcp_stack["subject"],
    )
    wrong_client_status, wrong_client_body = request_json(f"{gateway_url}mcp", token=wrong_client_token, payload=payload)
    assert wrong_client_status == 400
    assert wrong_client_body["error"]["code"] == -32602
    assert "Unknown tool" in wrong_client_body["error"]["message"]
    v1_token = build_token(
        mcp_stack["private_key"],
        tenant_id=mcp_stack["tenant_id"],
        audience=mcp_stack["audience"],
        scope=mcp_stack["scope"],
        issuer=mcp_stack["issuer"],
        authorized_client="synthetic-agent-c",
        subject=mcp_stack["subject"],
        version="1.0",
    )
    v1_status, v1_body = request_json(f"{gateway_url}mcp", token=v1_token, payload=payload)
    assert v1_status == 400
    assert v1_body["error"]["code"] == -32602
    assert "Unknown tool" in v1_body["error"]["message"]
    after = read_backend_debug_state(mcp_stack["env"])
    assert after["tool_calls_total"] == before["tool_calls_total"]


def test_solo_agentgateway_mcp_rejects_invalid_jwt_matrix(mcp_stack: dict[str, object]):
    gateway_url = mcp_stack["gateway_url"]
    payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": "get_account_summary", "arguments": {"account_id": "acct-1001"}},
        "id": "jwt-matrix",
    }
    valid_token = build_token(
        mcp_stack["private_key"],
        tenant_id=mcp_stack["tenant_id"],
        audience=mcp_stack["audience"],
        scope=mcp_stack["scope"],
        issuer=mcp_stack["issuer"],
        authorized_client=mcp_stack["authorized_client"],
        subject=mcp_stack["subject"],
    )
    authn_cases = [
        ("missing token", None, 401),
        ("malformed token", "not-a-jwt", 401),
        ("wrong audience", build_token(mcp_stack["private_key"], tenant_id=mcp_stack["tenant_id"], audience="api://wrong-audience", scope=mcp_stack["scope"], issuer=mcp_stack["issuer"], authorized_client=mcp_stack["authorized_client"], subject=mcp_stack["subject"]), 401),
        ("wrong issuer", build_token(mcp_stack["private_key"], tenant_id=mcp_stack["tenant_id"], audience=mcp_stack["audience"], scope=mcp_stack["scope"], issuer="https://login.microsoftonline.com/other/v2.0", authorized_client=mcp_stack["authorized_client"], subject=mcp_stack["subject"]), 401),
        ("expired token", build_token(mcp_stack["private_key"], tenant_id=mcp_stack["tenant_id"], audience=mcp_stack["audience"], scope=mcp_stack["scope"], issuer=mcp_stack["issuer"], authorized_client=mcp_stack["authorized_client"], subject=mcp_stack["subject"], expiration_offset=-300), 401),
        ("not yet valid token", build_token(mcp_stack["private_key"], tenant_id=mcp_stack["tenant_id"], audience=mcp_stack["audience"], scope=mcp_stack["scope"], issuer=mcp_stack["issuer"], authorized_client=mcp_stack["authorized_client"], subject=mcp_stack["subject"], not_yet_valid=True), 401),
        ("tampered signature", tamper_signature(valid_token), 401),
        ("wrong signing algorithm", build_token(mcp_stack["private_key"], tenant_id=mcp_stack["tenant_id"], audience=mcp_stack["audience"], scope=mcp_stack["scope"], issuer=mcp_stack["issuer"], authorized_client=mcp_stack["authorized_client"], subject=mcp_stack["subject"], algorithm="HS256", signing_secret="this-is-a-long-synthetic-hs256-secret-for-pytest-2026"), 401),
    ]
    for label, token, expected_status in authn_cases:
        before = read_backend_debug_state(mcp_stack["env"])
        status, body = request_json(f"{gateway_url}mcp", token=token, payload=payload)
        after = read_backend_debug_state(mcp_stack["env"])
        assert status == expected_status, f"{label} unexpectedly returned {status}: {body}"
        assert "error" in body
        assert "jsonrpc" not in body
        leaked = json.dumps(body, sort_keys=True)
        for blocked in ["acct-1001", "account_id", "user-12345", "user-67890", "synthetic-agent-b", "synthetic-agent-c", "@example.com", "not-a-jwt"]:
            assert blocked not in leaked.lower(), f"{label} leaked sensitive material: {body}"
        assert after["tool_calls_total"] == before["tool_calls_total"]

    authz_cases = [
        ("wrong tenant", build_token(mcp_stack["private_key"], tenant_id="99999999-8888-7777-6666-555555444444", audience=mcp_stack["audience"], scope=mcp_stack["scope"], issuer=mcp_stack["issuer"], authorized_client=mcp_stack["authorized_client"], subject=mcp_stack["subject"])),
        ("wrong client", build_token(mcp_stack["private_key"], tenant_id=mcp_stack["tenant_id"], audience=mcp_stack["audience"], scope=mcp_stack["scope"], issuer=mcp_stack["issuer"], authorized_client="synthetic-agent-c", subject=mcp_stack["subject"])),
        ("wrong scope", build_token(mcp_stack["private_key"], tenant_id=mcp_stack["tenant_id"], audience=mcp_stack["audience"], scope="Other.Scope", issuer=mcp_stack["issuer"], authorized_client=mcp_stack["authorized_client"], subject=mcp_stack["subject"])),
    ]
    for label, token in authz_cases:
        before = read_backend_debug_state(mcp_stack["env"])
        status, body = request_json(f"{gateway_url}mcp", token=token, payload=payload)
        after = read_backend_debug_state(mcp_stack["env"])
        assert status == 400, f"{label} unexpectedly accepted: {status} {body}"
        assert body["error"]["code"] == -32602
        assert "Unknown tool" in body["error"]["message"]
        assert after["tool_calls_total"] == before["tool_calls_total"]


def test_solo_agentgateway_mcp_write_idempotency_replay_and_conflict_are_rejected(mcp_stack: dict[str, object]):
    gateway_url = mcp_stack["gateway_url"]
    token = build_token(
        mcp_stack["private_key"],
        tenant_id=mcp_stack["tenant_id"],
        audience=mcp_stack["audience"],
        scope=mcp_stack["scope"],
        issuer=mcp_stack["issuer"],
        authorized_client=mcp_stack["authorized_client"],
        subject=mcp_stack["subject"],
    )
    initial_payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": "create_transfer", "arguments": {"from_account": "acct-1001", "to_account": "acct-2002", "amount": 25.0, "confirmation": "yes"}},
        "id": "idempotency-1",
    }
    first_status, first_body = request_json(
        f"{gateway_url}mcp",
        token=token,
        payload=initial_payload,
        extra_headers={"X-Idempotency-Key": "transfer-123"},
    )
    assert first_status == 200
    first_transfer_id = first_body["result"]["structuredContent"].get("transfer_id")
    assert first_transfer_id is not None

    duplicate_status, duplicate_body = request_json(
        f"{gateway_url}mcp",
        token=token,
        payload=initial_payload,
        extra_headers={"X-Idempotency-Key": "transfer-123"},
    )
    assert duplicate_status == 200
    assert duplicate_body["result"]["structuredContent"].get("transfer_id") == first_transfer_id

    conflicting_payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": "create_transfer", "arguments": {"from_account": "acct-1001", "to_account": "acct-2002", "amount": 42.0, "confirmation": "yes"}},
        "id": "idempotency-conflict",
    }
    conflict_status, conflict_body = request_json(
        f"{gateway_url}mcp",
        token=token,
        payload=conflicting_payload,
        extra_headers={"X-Idempotency-Key": "transfer-123"},
    )
    assert conflict_status in {400, 409}
    assert conflict_body["jsonrpc"] == "2.0"
    assert "error" in conflict_body

    missing_key_status, missing_key_body = request_json(
        f"{gateway_url}mcp",
        token=token,
        payload={"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "create_transfer", "arguments": {"from_account": "acct-1001", "to_account": "acct-2002", "amount": 10.0, "confirmation": "yes"}}, "id": "missing-idempotency"},
    )
    assert missing_key_status in {400, 401, 403}
    assert missing_key_body["jsonrpc"] == "2.0"
    assert "error" in missing_key_body


def test_solo_agentgateway_mcp_unknown_tool_is_denied(mcp_stack: dict[str, object]):
    gateway_url = mcp_stack["gateway_url"]
    before = read_backend_debug_state(mcp_stack["env"])
    token = build_token(
        mcp_stack["private_key"],
        tenant_id=mcp_stack["tenant_id"],
        audience=mcp_stack["audience"],
        scope=mcp_stack["scope"],
        issuer=mcp_stack["issuer"],
        authorized_client=mcp_stack["authorized_client"],
        subject=mcp_stack["subject"],
    )
    payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": "delete_account", "arguments": {"account_id": "acct-9999"}},
        "id": "unknown-tool-check",
    }
    status, body = request_json(f"{gateway_url}mcp", token=token, payload=payload)
    after = read_backend_debug_state(mcp_stack["env"])
    assert status == 400
    assert body["error"]["code"] == -32602
    assert "Unknown tool" in body["error"]["message"]
    assert after["tool_calls_total"] == before["tool_calls_total"]
    assert after["transfer_attempts_total"] == before["transfer_attempts_total"]
    assert after["transfer_mutations_total"] == before["transfer_mutations_total"]


def test_solo_agentgateway_mcp_missing_token_rejected(mcp_stack: dict[str, object]):
    gateway_url = mcp_stack["gateway_url"]
    before = read_backend_debug_state(mcp_stack["env"])
    payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": "get_account_summary", "arguments": {"account_id": "acct-1001"}},
        "id": "missing-token-check",
    }
    status, body = request_json(f"{gateway_url}mcp", payload=payload)
    after = read_backend_debug_state(mcp_stack["env"])
    assert status == 401
    assert "error" in body
    assert "jsonrpc" not in body
    assert "acct-1001" not in json.dumps(body, sort_keys=True)
    assert after["tool_calls_total"] == before["tool_calls_total"]
