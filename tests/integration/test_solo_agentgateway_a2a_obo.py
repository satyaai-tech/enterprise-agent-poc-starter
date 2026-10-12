from __future__ import annotations

import base64
import json
import os
import re
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
from a2a.types import AgentCard, SendMessageSuccessResponse
from cryptography.hazmat.primitives.asymmetric import rsa

REPO_ROOT = Path(__file__).resolve().parents[2]
SPIKE_DIR = REPO_ROOT / "experiments" / "solo-agentgateway" / "a2a-obo"
COMPOSE_FILE = SPIKE_DIR / "compose.yaml"


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def unique_compose_env(*, host_port: int | None = None, project_name: str | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env["COMPOSE_PROJECT_NAME"] = project_name or f"solo-a2a-{uuid.uuid4().hex[:8]}"
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


def request_json(
    url: str,
    *,
    token: str | None = None,
    method: str = "GET",
    payload: dict[str, object] | None = None,
    correlation_id: str = "corr-a2a-test",
) -> tuple[int, dict[str, object]]:
    headers = {"Content-Type": "application/json", "X-Correlation-Id": correlation_id}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(
        url,
        headers=headers,
        method=method,
        data=None if payload is None else json.dumps(payload).encode("utf-8"),
    )
    try:
        with urlopen(request, timeout=10) as response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body)
    except HTTPError as error:
        text = error.read().decode("utf-8")
        if not text:
            return error.code, {"jsonrpc": "2.0", "error": {"code": -32001, "message": "empty response"}}
        try:
            return error.code, json.loads(text)
        except json.JSONDecodeError:
            return error.code, {"jsonrpc": "2.0", "error": {"code": -32001, "message": text}}
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


def render_config(*, tmp_dir: Path, tenant_id: str, issuer: str, audience: str, scope: str, authorized_client: str) -> tuple[Path, Path, Path, object]:
    fixture_dir = tmp_dir / "fixtures"
    fixture_dir.mkdir(parents=True, exist_ok=True)
    private_key, public_jwk = rsa_key_pair()
    jwks_path = fixture_dir / "jwks.json"
    jwks_path.write_text(json.dumps({"keys": [public_jwk]}, indent=2), encoding="utf-8")

    config_path = tmp_dir / "agentgateway-config.yaml"
    env = unique_compose_env(host_port=get_free_port())
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


@pytest.fixture
def a2a_stack(tmp_path: Path):
    tenant_id = "11111111-2222-3333-4444-555555666666"
    issuer = f"https://login.microsoftonline.com/{tenant_id}/v2.0"
    audience = "api://agent-b-example"
    scope = "AgentB.Access"
    authorized_client = "synthetic-agent-a"
    subject = "user-12345"

    jwks_path, config_path, fixture_dir, private_key = render_config(
        tmp_dir=tmp_path,
        tenant_id=tenant_id,
        issuer=issuer,
        audience=audience,
        scope=scope,
        authorized_client=authorized_client,
    )
    gateway_port = get_free_port()
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
        wait_for_http(f"{gateway_url}.well-known/agent.json")
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


@pytest.mark.parametrize(
    ("case_name", "token_factory"),
    [
        pytest.param("missing_token", lambda *, value=None, **kwargs: None, id="missing_token"),
        pytest.param("malformed_token", lambda *, value=None, **kwargs: "not-a-jwt", id="malformed_token"),
        pytest.param("expired", lambda *, private_key, tenant_id, audience, scope, issuer, authorized_client, subject, **kwargs: build_token(private_key, tenant_id=tenant_id, audience=audience, scope=scope, issuer=issuer, authorized_client=authorized_client, subject=subject, expired=True), id="expired"),
        pytest.param("future_nbf", lambda *, private_key, tenant_id, audience, scope, issuer, authorized_client, subject, **kwargs: build_token(private_key, tenant_id=tenant_id, audience=audience, scope=scope, issuer=issuer, authorized_client=authorized_client, subject=subject, not_yet_valid=True), id="future_nbf"),
        pytest.param("missing_iat", lambda *, private_key, tenant_id, audience, scope, issuer, authorized_client, subject, **kwargs: build_token(private_key, tenant_id=tenant_id, audience=audience, scope=scope, issuer=issuer, authorized_client=authorized_client, subject=subject, include_iat=False), id="missing_iat"),
        pytest.param("tampered_signature", lambda *, private_key, tenant_id, audience, scope, issuer, authorized_client, subject, **kwargs: tamper_signature(build_token(private_key, tenant_id=tenant_id, audience=audience, scope=scope, issuer=issuer, authorized_client=authorized_client, subject=subject)), id="tampered_signature"),
        pytest.param("wrong_algorithm", lambda *, private_key, tenant_id, audience, scope, issuer, authorized_client, subject, **kwargs: build_token(private_key, tenant_id=tenant_id, audience=audience, scope=scope, issuer=issuer, authorized_client=authorized_client, subject=subject, algorithm="HS256", signing_secret="not-a-private-key"), id="wrong_algorithm"),
        pytest.param("wrong_issuer", lambda *, private_key, tenant_id, audience, scope, issuer, authorized_client, subject, **kwargs: build_token(private_key, tenant_id=tenant_id, audience=audience, scope=scope, issuer="https://login.microsoftonline.com/other/v2.0", authorized_client=authorized_client, subject=subject), id="wrong_issuer"),
        pytest.param("wrong_tenant", lambda *, private_key, tenant_id, audience, scope, issuer, authorized_client, subject, **kwargs: build_token(private_key, tenant_id="99999999-9999-9999-9999-999999999999", audience=audience, scope=scope, issuer=issuer, authorized_client=authorized_client, subject=subject), id="wrong_tenant"),
        pytest.param("wrong_audience", lambda *, private_key, tenant_id, audience, scope, issuer, authorized_client, subject, **kwargs: build_token(private_key, tenant_id=tenant_id, audience="api://wrong-audience", scope=scope, issuer=issuer, authorized_client=authorized_client, subject=subject), id="wrong_audience"),
        pytest.param("wrong_scope", lambda *, private_key, tenant_id, audience, scope, issuer, authorized_client, subject, **kwargs: build_token(private_key, tenant_id=tenant_id, audience=audience, scope="Other.Access", issuer=issuer, authorized_client=authorized_client, subject=subject), id="wrong_scope"),
        pytest.param("AgentB.AccessExtra", lambda *, private_key, tenant_id, audience, scope, issuer, authorized_client, subject, **kwargs: build_token(private_key, tenant_id=tenant_id, audience=audience, scope="AgentB.AccessExtra", issuer=issuer, authorized_client=authorized_client, subject=subject), id="AgentB.AccessExtra"),
        pytest.param("missing_azp", lambda *, private_key, tenant_id, audience, scope, issuer, authorized_client, subject, **kwargs: build_token(private_key, tenant_id=tenant_id, audience=audience, scope=scope, issuer=issuer, authorized_client=authorized_client, subject=subject, overrides={"azp": None}), id="missing_azp"),
        pytest.param("wrong_azp", lambda *, private_key, tenant_id, audience, scope, issuer, authorized_client, subject, **kwargs: build_token(private_key, tenant_id=tenant_id, audience=audience, scope=scope, issuer=issuer, authorized_client="not-agent-a", subject=subject), id="wrong_azp"),
        pytest.param("missing_appid_v1", lambda *, private_key, tenant_id, audience, scope, issuer, authorized_client, subject, **kwargs: build_token(private_key, tenant_id=tenant_id, audience=audience, scope=scope, issuer=issuer, authorized_client=authorized_client, subject=subject, version="1.0", overrides={"appid": None}), id="missing_appid_for_v1"),
        pytest.param("wrong_appid_v1", lambda *, private_key, tenant_id, audience, scope, issuer, authorized_client, subject, **kwargs: build_token(private_key, tenant_id=tenant_id, audience=audience, scope=scope, issuer=issuer, authorized_client="not-agent-a", subject=subject, version="1.0"), id="wrong_appid_for_v1"),
        pytest.param("agent_a_token_used_as_agent_b_token", lambda *, private_key, tenant_id, audience, scope, issuer, authorized_client, subject, **kwargs: build_token(private_key, tenant_id=tenant_id, audience="api://agent-a-example", scope="AgentA.Access", issuer=issuer, authorized_client=authorized_client, subject=subject), id="agent_a_token_used_as_agent_b_token"),
    ],
)
def test_solo_agentgateway_a2a_negative_matrix(a2a_stack: dict[str, object], case_name: str, token_factory):
    gateway_url = a2a_stack["gateway_url"]
    valid_token = build_token(
        a2a_stack["private_key"],
        tenant_id=a2a_stack["tenant_id"],
        audience=a2a_stack["audience"],
        scope=a2a_stack["scope"],
        issuer=a2a_stack["issuer"],
        authorized_client=a2a_stack["authorized_client"],
        subject=a2a_stack["subject"],
    )
    before_count = request_json(f"{gateway_url}__debug/requests", token=valid_token)[1]["protected_message_count"]
    payload = {
        "jsonrpc": "2.0",
        "method": "message/send",
        "params": {"message": {"role": "user", "parts": [{"kind": "text", "text": "hello from agent a"}]}},
        "id": "case-" + case_name,
    }
    token = token_factory(
        private_key=a2a_stack["private_key"],
        tenant_id=a2a_stack["tenant_id"],
        audience=a2a_stack["audience"],
        scope=a2a_stack["scope"],
        issuer=a2a_stack["issuer"],
        authorized_client=a2a_stack["authorized_client"],
        subject=a2a_stack["subject"],
    ) if case_name not in {"missing_token", "malformed_token"} else None
    if case_name == "missing_token":
        status, body = request_json(f"{gateway_url}a2a", method="POST", payload=payload)
    elif case_name == "malformed_token":
        status, body = request_json(f"{gateway_url}a2a", token="not-a-jwt", method="POST", payload=payload)
    else:
        status, body = request_json(f"{gateway_url}a2a", token=token, method="POST", payload=payload)
    assert status in {401, 403}
    assert body["jsonrpc"] == "2.0"
    assert "error" in body
    assert "message" in body["error"]
    after_count = request_json(f"{gateway_url}__debug/requests", token=valid_token)[1]["protected_message_count"]
    assert before_count == after_count


def test_solo_agentgateway_a2a_public_agent_card(a2a_stack: dict[str, object]):
    gateway_url = a2a_stack["gateway_url"]
    status, body = request_json(f"{gateway_url}.well-known/agent.json")
    assert status == 200
    agent_card = AgentCard.model_validate(body)
    assert agent_card.name == "mock-agent-b"
    assert agent_card.protocolVersion == "0.2.5"
    assert agent_card.url == "http://mock-agent-b:8080"


def test_solo_agentgateway_a2a_agent_card_route_precedence(a2a_stack: dict[str, object]):
    gateway_url = a2a_stack["gateway_url"]
    status, body = request_json(f"{gateway_url}.well-known/agent.json", token="not-a-jwt")
    assert status == 200
    assert body["name"] == "mock-agent-b"
    assert body["protocolVersion"] == "0.2.5"


def test_solo_agentgateway_a2a_message_route_remains_protected(a2a_stack: dict[str, object]):
    gateway_url = a2a_stack["gateway_url"]
    payload = {"jsonrpc": "2.0", "method": "message/send", "params": {"message": {"messageId": "protected-check", "role": "user", "parts": [{"kind": "text", "text": "hello"}]}}, "id": "protected-check"}
    status, body = request_json(f"{gateway_url}a2a", method="POST", payload=payload)
    assert status == 401
    assert "error" in body
    assert "message" in body["error"]
    assert "token" in body["error"]["message"].lower() or "bearer" in body["error"]["message"].lower() or "authentication" in body["error"]["message"].lower()


def test_solo_agentgateway_a2a_valid_token_b_is_forwarded(a2a_stack: dict[str, object]):
    gateway_url = a2a_stack["gateway_url"]
    valid_token = build_token(
        a2a_stack["private_key"],
        tenant_id=a2a_stack["tenant_id"],
        audience=a2a_stack["audience"],
        scope=a2a_stack["scope"],
        issuer=a2a_stack["issuer"],
        authorized_client=a2a_stack["authorized_client"],
        subject=a2a_stack["subject"],
    )
    payload = {"jsonrpc": "2.0", "method": "message/send", "params": {"message": {"messageId": "valid-forward", "role": "user", "parts": [{"kind": "text", "text": "hello from agent a"}]}}, "id": "valid-forward"}
    status, body = request_json(f"{gateway_url}a2a", token=valid_token, method="POST", payload=payload)
    assert status == 200
    response = SendMessageSuccessResponse.model_validate(body)
    assert response.jsonrpc == "2.0"
    assert response.result.kind == "message"
    assert response.result.role == "agent"
    assert response.result.parts[0].root.text == "hello from mock-agent-b"


def test_solo_agentgateway_a2a_agent_b_independently_validates_token_b(a2a_stack: dict[str, object]):
    gateway_url = a2a_stack["gateway_url"]
    valid_token = build_token(
        a2a_stack["private_key"],
        tenant_id=a2a_stack["tenant_id"],
        audience=a2a_stack["audience"],
        scope=a2a_stack["scope"],
        issuer=a2a_stack["issuer"],
        authorized_client=a2a_stack["authorized_client"],
        subject=a2a_stack["subject"],
    )
    lost_scope = build_token(
        a2a_stack["private_key"],
        tenant_id=a2a_stack["tenant_id"],
        audience=a2a_stack["audience"],
        scope="Wrong.Access",
        issuer=a2a_stack["issuer"],
        authorized_client=a2a_stack["authorized_client"],
        subject=a2a_stack["subject"],
    )
    status, body = request_json(f"{gateway_url}a2a", token=lost_scope, method="POST", payload={"jsonrpc": "2.0", "method": "message/send", "params": {"message": {"role": "user", "parts": [{"kind": "text", "text": "bad"}]}}, "id": "scope-check"})
    assert status == 403
    assert "error" in body
    assert "message" in body["error"]

    status, body = request_json(f"{gateway_url}a2a", token=valid_token, method="POST", payload={"jsonrpc": "2.0", "method": "message/send", "params": {"message": {"messageId": "good-check", "role": "user", "parts": [{"kind": "text", "text": "good"}]}}, "id": "good-check"})
    assert status == 200
    assert body["result"]["metadata"]["audience_ok"] is True
    assert body["result"]["metadata"]["scope_ok"] is True
    assert body["result"]["metadata"]["issuer_ok"] is True
    assert body["result"]["metadata"]["tenant_ok"] is True
    assert body["result"]["metadata"]["client_ok"] is True
    assert body["result"]["metadata"]["authenticated"] is True


def test_solo_agentgateway_a2a_jwks_unavailable_on_cold_start_fails_closed(tmp_path: Path):
    tenant_id = "11111111-2222-3333-4444-555555666666"
    issuer = f"https://login.microsoftonline.com/{tenant_id}/v2.0"
    audience = "api://agent-b-example"
    scope = "AgentB.Access"
    authorized_client = "synthetic-agent-a"
    private_key, _ = rsa_key_pair()
    token = build_token(private_key, tenant_id=tenant_id, audience=audience, scope=scope, issuer=issuer, authorized_client=authorized_client, subject="user-12345")

    missing_dir = tmp_path / "missing-jwks"
    config_path = tmp_path / "agentgateway-config.yaml"
    env = unique_compose_env(host_port=get_free_port())
    env.update(
        {
            "TENANT_ID": tenant_id,
            "ISSUER": issuer,
            "EXPECTED_AUDIENCE": audience,
            "EXPECTED_SCOPE": scope,
            "AUTHORIZED_CLIENT": authorized_client,
            "AG_CONFIG_PATH": str(config_path),
            "JWKS_FILE_DIR": str(missing_dir),
        }
    )
    subprocess.run(["python3", str(SPIKE_DIR / "render_config.py")], cwd=REPO_ROOT, env=env, check=True)
    run_compose("up", "-d", "--build", env=env)
    gateway_url = f"http://localhost:{env['HOST_PORT']}/"
    try:
        wait_for_http(f"{gateway_url}.well-known/agent.json")
        before = request_json(f"{gateway_url}__debug/requests", token=build_token(private_key, tenant_id=tenant_id, audience=audience, scope=scope, issuer=issuer, authorized_client=authorized_client, subject="user-12345"))[1].get("protected_message_count", 0)
        status, body = request_json(f"{gateway_url}a2a", token=token, method="POST", payload={"jsonrpc": "2.0", "method": "message/send", "params": {"message": {"messageId": "cold-start", "role": "user", "parts": [{"kind": "text", "text": "cold start"}]}}, "id": "cold-start"})
        assert status in {401, 403}
        assert status != 200
        assert "error" in body
        assert isinstance(body["error"], dict)
        assert "message" in body["error"]
        serialized = json.dumps(body, sort_keys=True).lower()
        assert "secret" not in serialized
        assert "token" in serialized or "authentication" in serialized or "unauthorized" in serialized or "forbidden" in serialized
        after = request_json(f"{gateway_url}__debug/requests", token=build_token(private_key, tenant_id=tenant_id, audience=audience, scope=scope, issuer=issuer, authorized_client=authorized_client, subject="user-12345"))[1].get("protected_message_count", 0)
        assert after == before
    finally:
        subprocess.run(["docker", "compose", "-f", str(COMPOSE_FILE), "down", "-v", "--remove-orphans"], cwd=REPO_ROOT, env=env, text=True, capture_output=True, check=False)


def test_solo_agentgateway_a2a_cached_key_behavior_after_initial_fetch(a2a_stack: dict[str, object]):
    gateway_url = a2a_stack["gateway_url"]
    valid_token = build_token(
        a2a_stack["private_key"],
        tenant_id=a2a_stack["tenant_id"],
        audience=a2a_stack["audience"],
        scope=a2a_stack["scope"],
        issuer=a2a_stack["issuer"],
        authorized_client=a2a_stack["authorized_client"],
        subject=a2a_stack["subject"],
    )
    payload = {"jsonrpc": "2.0", "method": "message/send", "params": {"message": {"messageId": "cache-check", "role": "user", "parts": [{"kind": "text", "text": "hello"}]}}, "id": "cache-check"}
    status, _ = request_json(f"{gateway_url}a2a", token=valid_token, method="POST", payload=payload)
    assert status == 200

    current_key = a2a_stack["jwks_path"].read_text(encoding="utf-8")
    replacement_private_key, replacement_jwk = rsa_key_pair()
    a2a_stack["jwks_path"].write_text(json.dumps({"keys": [replacement_jwk]}, indent=2), encoding="utf-8")
    rotated_token = build_token(
        replacement_private_key,
        tenant_id=a2a_stack["tenant_id"],
        audience=a2a_stack["audience"],
        scope=a2a_stack["scope"],
        issuer=a2a_stack["issuer"],
        authorized_client=a2a_stack["authorized_client"],
        subject=a2a_stack["subject"],
    )
    before = request_json(f"{gateway_url}__debug/requests", token=valid_token)[1]["protected_message_count"]
    status, body = request_json(f"{gateway_url}a2a", token=rotated_token, method="POST", payload=payload)
    assert status in {401, 403}
    assert status != 200
    serialized = json.dumps(body, sort_keys=True).lower()
    assert "token" not in serialized or "authentication" in serialized or "invalid" in serialized
    assert "secret" not in serialized
    assert "oid" not in serialized
    assert "sub" not in serialized
    after = request_json(f"{gateway_url}__debug/requests", token=valid_token)[1]["protected_message_count"]
    assert after == before
    a2a_stack["jwks_path"].write_text(current_key, encoding="utf-8")


def test_solo_agentgateway_a2a_compose_has_no_published_ports():
    compose_text = (SPIKE_DIR / "compose.yaml").read_text(encoding="utf-8")
    service_blocks = re.findall(r"^(  [a-zA-Z0-9-]+):\n((?:    .*\n)+)", compose_text, re.MULTILINE)
    for service_name, block in service_blocks:
        service_name = service_name.strip()
        if service_name in {"mock-agent-b", "jwks-fixture"}:
            assert "    ports:" not in block


def test_solo_agentgateway_a2a_logs_do_not_contain_canary_tokens_or_secrets(tmp_path: Path):
    tenant_id = "11111111-2222-3333-4444-555555666666"
    issuer = f"https://login.microsoftonline.com/{tenant_id}/v2.0"
    env = unique_compose_env(host_port=get_free_port())
    env.update(
        {
            "TENANT_ID": tenant_id,
            "ISSUER": issuer,
            "EXPECTED_AUDIENCE": "api://agent-b-example",
            "EXPECTED_SCOPE": "AgentB.Access",
            "AUTHORIZED_CLIENT": "synthetic-agent-a",
            "AG_CONFIG_PATH": str(tmp_path / "agentgateway-config.yaml"),
            "JWKS_FILE_DIR": str(tmp_path),
            "CANARY_TOKEN": "synthetic-canary-token-0123456789",
            "CANARY_SECRET": "synthetic-canary-secret-0123456789",
        }
    )
    subprocess.run(["python3", str(SPIKE_DIR / "render_config.py")], cwd=REPO_ROOT, env=env, check=True)
    run_compose("up", "-d", "--build", env=env)
    try:
        logs = run_compose("logs", env=env).stdout.lower()
        assert "synthetic-canary-token-0123456789" not in logs
        assert "synthetic-canary-secret-0123456789" not in logs
        assert "canary" not in logs
    finally:
        subprocess.run(["docker", "compose", "-f", str(COMPOSE_FILE), "down", "-v", "--remove-orphans"], cwd=REPO_ROOT, env=env, text=True, capture_output=True, check=False)


def test_solo_agentgateway_a2a_protected_counter_only_tracks_protected_messages(a2a_stack: dict[str, object]):
    gateway_url = a2a_stack["gateway_url"]
    valid_token = build_token(
        a2a_stack["private_key"],
        tenant_id=a2a_stack["tenant_id"],
        audience=a2a_stack["audience"],
        scope=a2a_stack["scope"],
        issuer=a2a_stack["issuer"],
        authorized_client=a2a_stack["authorized_client"],
        subject=a2a_stack["subject"],
    )
    before = request_json(f"{gateway_url}__debug/requests", token=valid_token)[1]["protected_message_count"]
    request_json(f"{gateway_url}.well-known/agent.json")
    status, _ = request_json(f"{gateway_url}a2a", token=valid_token, method="POST", payload={"jsonrpc": "2.0", "method": "message/send", "params": {"message": {"messageId": "count-check", "role": "user", "parts": [{"kind": "text", "text": "count"}]}}, "id": "count-check"})
    assert status == 200
    after = request_json(f"{gateway_url}__debug/requests", token=valid_token)[1]["protected_message_count"]
    assert after == before + 1


def test_solo_agentgateway_a2a_v1_token_is_valid_with_appid(a2a_stack: dict[str, object]):
    gateway_url = a2a_stack["gateway_url"]
    valid_v1 = build_token(
        a2a_stack["private_key"],
        tenant_id=a2a_stack["tenant_id"],
        audience=a2a_stack["audience"],
        scope=a2a_stack["scope"],
        issuer=a2a_stack["issuer"],
        authorized_client=a2a_stack["authorized_client"],
        subject=a2a_stack["subject"],
        version="1.0",
    )
    status, body = request_json(f"{gateway_url}a2a", token=valid_v1, method="POST", payload={"jsonrpc": "2.0", "method": "message/send", "params": {"message": {"messageId": "v1-check", "role": "user", "parts": [{"kind": "text", "text": "v1"}]}}, "id": "v1-check"})
    assert status == 200
    assert body["result"]["metadata"]["authenticated"] is True


def test_compose_config_validation(tmp_path: Path):
    tenant_id = "11111111-2222-3333-4444-555555666666"
    issuer = f"https://login.microsoftonline.com/{tenant_id}/v2.0"
    audience = "api://agent-b-example"
    scope = "AgentB.Access"
    authorized_client = "synthetic-agent-a"
    config_path = tmp_path / "agentgateway-config.yaml"
    env = unique_compose_env(host_port=get_free_port())
    env.update(
        {
            "TENANT_ID": tenant_id,
            "ISSUER": issuer,
            "EXPECTED_AUDIENCE": audience,
            "EXPECTED_SCOPE": scope,
            "AUTHORIZED_CLIENT": authorized_client,
            "AG_CONFIG_PATH": str(config_path),
            "JWKS_FILE_DIR": str(SPIKE_DIR / "fixtures"),
        }
    )
    subprocess.run(["python3", str(SPIKE_DIR / "render_config.py")], cwd=REPO_ROOT, env=env, check=True)
    run_compose("config", env=env)


def test_solo_agentgateway_a2a_all_required_matrix_items_are_named():
    items = [
        "missing_token",
        "malformed_token",
        "expired",
        "future_nbf",
        "missing_iat",
        "tampered_signature",
        "wrong_algorithm",
        "wrong_issuer",
        "wrong_tenant",
        "wrong_audience",
        "wrong_scope",
        "AgentB.AccessExtra",
        "missing_azp",
        "wrong_azp",
        "missing_appid_for_v1",
        "wrong_appid_for_v1",
        "agent_a_token_used_as_agent_b_token",
    ]
    assert len(items) == 17
