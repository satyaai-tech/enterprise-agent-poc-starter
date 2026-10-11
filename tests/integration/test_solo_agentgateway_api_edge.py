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
from cryptography.hazmat.primitives.asymmetric import rsa

REPO_ROOT = Path(__file__).resolve().parents[2]
SPIKE_DIR = REPO_ROOT / "experiments" / "solo-agentgateway" / "api-edge"
COMPOSE_FILE = SPIKE_DIR / "compose.yaml"


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def unique_compose_env(*, host_port: int | None = None, project_name: str | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env["COMPOSE_PROJECT_NAME"] = project_name or f"solo-edge-{uuid.uuid4().hex[:8]}"
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


def request_json(url: str, *, token: str | None = None, correlation_id: str = "corr-test") -> tuple[int, dict[str, object]]:
    headers = {"Content-Type": "application/json", "X-Correlation-Id": correlation_id}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, headers=headers, method="GET")
    try:
        with urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        text = error.read().decode("utf-8")
        if not text:
            return error.code, {"status": "FAIL", "error": "empty response"}
        try:
            return error.code, json.loads(text)
        except json.JSONDecodeError:
            return error.code, {"status": "FAIL", "error": text}
    except URLError as error:
        raise RuntimeError(f"Request failed: {error}") from error


def rsa_key_pair():
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
    expired: bool = False,
    expiration_offset: int | None = None,
    not_yet_valid: bool = False,
    include_iat: bool = True,
    algorithm: str = "RS256",
    signing_secret: str | None = None,
    overrides: dict[str, object] | None = None,
) -> str:
    now = int(datetime.now(timezone.utc).timestamp())
    payload = {
        "iss": issuer,
        "aud": audience,
        "tid": tenant_id,
        "scp": scope,
        "azp": authorized_client,
        "iat": now - 120,
        "nbf": now - 60,
        "exp": now + 3600,
    }
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


def render_config(*, tmp_dir: Path, tenant_id: str, issuer: str, audience: str, scope: str, authorized_client: str) -> tuple[Path, Path]:
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
    return jwks_path, config_path, private_key


def test_compose_config_validation():
    env = unique_compose_env(host_port=get_free_port())
    env.update({
        "AG_CONFIG_PATH": str(SPIKE_DIR / "agentgateway" / "config.yaml"),
        "JWKS_FILE_DIR": str(SPIKE_DIR / "fixtures"),
    })
    run_compose("config", env=env)


def test_solo_agentgateway_api_edge(tmp_path: Path):
    tenant_id = "11111111-2222-3333-4444-555555666666"
    issuer = f"https://login.microsoftonline.com/{tenant_id}/v2.0"
    audience = "api://agent-a-example"
    scope = "AgentA.Access"
    authorized_client = "synthetic-client"
    jwks_path, config_path, private_key = render_config(
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
        wait_for_http(gateway_url)

        valid_token = build_token(
            private_key,
            tenant_id=tenant_id,
            audience=audience,
            scope=scope,
            issuer=issuer,
            authorized_client=authorized_client,
        )
        status, body = request_json(gateway_url, token=valid_token)
        assert status == 200
        assert body["status"] == "ok"
        assert body["service"] == "mock-agent-a"
        assert body["authorization_present"] is False

        baseline_count = request_json(f"{gateway_url}__debug/requests", token=valid_token)[1]["request_count"]
        assert baseline_count >= 1

        near_boundary_token = build_token(
            private_key,
            tenant_id=tenant_id,
            audience=audience,
            scope=scope,
            issuer=issuer,
            authorized_client=authorized_client,
            expiration_offset=-30,
        )
        near_boundary_status, near_boundary_body = request_json(gateway_url, token=near_boundary_token)
        assert near_boundary_status in {200, 401, 403}, f"unexpected near-boundary status: {near_boundary_status} {near_boundary_body}"
        if near_boundary_status == 200:
            assert near_boundary_body["status"] == "ok"
        assert near_boundary_body.get("status") != "ok" or near_boundary_status == 200
        baseline_count = request_json(f"{gateway_url}__debug/requests", token=valid_token)[1]["request_count"]

        clearly_expired_token = build_token(
            private_key,
            tenant_id=tenant_id,
            audience=audience,
            scope=scope,
            issuer=issuer,
            authorized_client=authorized_client,
            expiration_offset=-300,
        )
        status, body = request_json(gateway_url, token=clearly_expired_token)
        assert status in {401, 403}, f"clearly expired token unexpectedly accepted: {status} {body}"
        assert body.get("status") != "ok", f"clearly expired token reached the upstream service: {body}"
        current_count = request_json(f"{gateway_url}__debug/requests", token=valid_token)[1]["request_count"]
        assert current_count == baseline_count, f"clearly expired token reached mock-agent-a: baseline={baseline_count} current={current_count}"

        rejection_cases = [
            ("missing token", None, None),
            ("malformed token", "not-a-jwt", None),
            ("not yet valid token", build_token(private_key, tenant_id=tenant_id, audience=audience, scope=scope, issuer=issuer, authorized_client=authorized_client, not_yet_valid=True), None),
            ("wrong audience", build_token(private_key, tenant_id=tenant_id, audience="api://agent-b-example", scope=scope, issuer=issuer, authorized_client=authorized_client), None),
            ("wrong tenant", build_token(private_key, tenant_id="22222222-3333-4444-5555-666666777777", audience=audience, scope=scope, issuer=issuer, authorized_client=authorized_client), None),
            ("wrong issuer", build_token(private_key, tenant_id=tenant_id, audience=audience, scope=scope, issuer="https://login.microsoftonline.com/other/v2.0", authorized_client=authorized_client), None),
            ("wrong scope", build_token(private_key, tenant_id=tenant_id, audience=audience, scope="Other.Scope", issuer=issuer, authorized_client=authorized_client), None),
            ("scope prefix not exact match", build_token(private_key, tenant_id=tenant_id, audience=audience, scope="AgentA.AccessExtra", issuer=issuer, authorized_client=authorized_client), None),
            ("missing iat", build_token(private_key, tenant_id=tenant_id, audience=audience, scope=scope, issuer=issuer, authorized_client=authorized_client, include_iat=False), None),
            ("wrong signing algorithm", build_token(private_key, tenant_id=tenant_id, audience=audience, scope=scope, issuer=issuer, authorized_client=authorized_client, algorithm="HS256", signing_secret="this-is-a-long-synthetic-hs256-secret-for-pytest-2026"), None),
            ("tampered signature", tamper_signature(valid_token), None),
        ]

        for label, token, _ in rejection_cases:
            status, body = request_json(gateway_url, token=token)
            assert status in {401, 403}, f"{label} unexpectedly accepted: {status} {body}"
            assert body.get("status") != "ok", f"{label} reached the upstream service: {body}"
            current_count = request_json(f"{gateway_url}__debug/requests", token=valid_token)[1]["request_count"]
            assert current_count == baseline_count, f"{label} reached mock-agent-a: baseline={baseline_count} current={current_count}"

        run_compose("down", "-v", env=env)

        broken_config = tmp_path / "broken-config.yaml"
        broken_config.write_text(
            """gateways:
  default:
    port: 8080
    bindAddress: 0.0.0.0
    jwtAuth:
      mode: strict
      issuer: "https://login.microsoftonline.com/11111111-2222-3333-4444-555555666666/v2.0"
      audiences:
        - "api://agent-a-example"
      jwks:
        url: "http://jwks-fixture-does-not-exist.invalid:8081/.well-known/jwks.json"
      jwtValidationOptions:
        requiredClaims:
          - exp
    authorization:
      rules:
        - allow: "jwt.iat > 0 && jwt.tid == '11111111-2222-3333-4444-555555666666' && jwt.azp == 'synthetic-client' && jwt.scp.split(' ').exists(scope, scope == 'AgentA.Access')"
routes:
  - name: mock-agent-a
    matches:
      - path:
          pathPrefix: /
    backends:
      - host: "mock-agent-a:8080"
""",
            encoding="utf-8",
        )
        broken_env = env.copy()
        broken_env["AG_CONFIG_PATH"] = str(broken_config)
        broken_env["COMPOSE_PROJECT_NAME"] = f"solo-edge-broken-{uuid.uuid4().hex[:8]}"
        broken_env["HOST_PORT"] = str(get_free_port())
        run_compose("up", "-d", "--build", env=broken_env)
        time.sleep(5)
        result = subprocess.run(
            ["docker", "compose", "-f", str(COMPOSE_FILE), "ps", "-a", "--format", "{{.Service}} {{.State}}"],
            cwd=REPO_ROOT,
            env=broken_env,
            text=True,
            capture_output=True,
            check=False,
        )
        assert "agentgateway exited" in result.stdout.lower() or "exited" in result.stdout.lower()
        run_compose("down", "-v", env=broken_env)
    finally:
        run_compose("down", "-v", env=env)


def test_jwks_cache_remains_after_outage(tmp_path: Path):
    tenant_id = "11111111-2222-3333-4444-555555666666"
    issuer = f"https://login.microsoftonline.com/{tenant_id}/v2.0"
    audience = "api://agent-a-example"
    scope = "AgentA.Access"
    authorized_client = "synthetic-client"
    jwks_path, config_path, private_key = render_config(
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
        wait_for_http(gateway_url)
        valid_token = build_token(
            private_key,
            tenant_id=tenant_id,
            audience=audience,
            scope=scope,
            issuer=issuer,
            authorized_client=authorized_client,
        )

        status, body = request_json(gateway_url, token=valid_token)
        assert status == 200
        assert body["service"] == "mock-agent-a"
        assert body["authorization_present"] is False

        run_compose("stop", "jwks-fixture", env=env)
        time.sleep(2)
        status_after_outage, body_after_outage = request_json(gateway_url, token=valid_token)
        assert status_after_outage == 200, f"JWKS outage unexpectedly broke a cached key: {body_after_outage}"
        assert body_after_outage["service"] == "mock-agent-a"
    finally:
        run_compose("up", "-d", "jwks-fixture", env=env)
        time.sleep(3)
        run_compose("down", "-v", env=env)
