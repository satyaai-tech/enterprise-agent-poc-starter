from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa


REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPO_ROOT / "infra" / "kong" / "spikes" / "external-authorizer" / "compose.yml"


def rsa_key_pair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(public_key))
    return private_key, public_jwk


def build_token(
    private_key,
    *,
    tenant_id: str,
    audience: str,
    scope: str,
    issuer: str,
    authorized_client: str,
    version: str = "2.0",
    expired: bool = False,
    kid: str = "synthetic-kid",
) -> str:
    now = int(datetime.now(timezone.utc).timestamp())
    payload = {
        "ver": version,
        "iss": issuer,
        "aud": audience,
        "tid": tenant_id,
        "scp": scope,
        "azp": authorized_client,
        "exp": now - 30 if expired else now + 3600,
        "nbf": now - 60,
        "iat": now - 120,
    }
    return jwt.encode(payload, private_key, algorithm="RS256", headers={"kid": kid})


def write_fixture_dir(*, public_jwk: dict[str, object], issuer: str, tmp_dir: Path) -> tuple[Path, Path, Path]:
    fixture_dir = tmp_dir / "fixtures"
    evidence_dir = tmp_dir / "evidence"
    state_dir = tmp_dir / "state"
    fixture_dir.mkdir(parents=True, exist_ok=True)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    fixture_jwk = dict(public_jwk)
    fixture_jwk["kid"] = "synthetic-kid"
    (fixture_dir / "openid-configuration.json").write_text(
        json.dumps({"issuer": issuer, "jwks_uri": "https://fixture.local/jwks"}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (fixture_dir / "jwks.json").write_text(
        json.dumps({"keys": [fixture_jwk]}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return fixture_dir, evidence_dir, state_dir


def compose_env(*, fixture_dir: Path, evidence_dir: Path, state_dir: Path, tenant_id: str, audience: str, scope: str, authorized_client: str) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "SPIKE_FIXTURE_DIR": str(fixture_dir),
            "SPIKE_EVIDENCE_DIR": str(evidence_dir),
            "SPIKE_STATE_DIR": str(state_dir),
            "SPIKE_TENANT_ID": tenant_id,
            "SPIKE_EXPECTED_AUDIENCE": audience,
            "SPIKE_EXPECTED_SCOPE": scope,
            "SPIKE_EXPECTED_AUTHORIZED_CLIENT": authorized_client,
            "KONG_HOST_PORT": "8080",
        }
    )
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
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(1)
    raise RuntimeError(f"Timed out waiting for {url}: {last_error}")


def request_json(url: str, *, token: str | None = None, correlation_id: str = "test-correlation") -> tuple[int, dict[str, object]]:
    headers = {"Content-Type": "application/json", "X-Correlation-Id": correlation_id}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, data=b"{}", headers=headers, method="POST")
    try:
        with urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8"))
    except URLError as error:
        raise RuntimeError(f"Request failed: {error}") from error


def latest_evidence(evidence_dir: Path) -> Path:
    candidates = sorted(evidence_dir.glob("phase-0-entra-authorized-client-validation-*.json"))
    if not candidates:
        raise AssertionError("No evidence files were created")
    return candidates[-1]


def test_minimal_spike_end_to_end(tmp_path: Path):
    private_key, public_jwk = rsa_key_pair()
    tenant_id = "11111111-2222-3333-4444-555555666666"
    audience = "api://agent-a-example"
    scope = "api://agent-a-client-id/AgentA.Access"
    issuer = f"https://login.microsoftonline.com/{tenant_id}/v2.0"
    authorized_client = "notebook-client"
    fixture_dir, evidence_dir, state_dir = write_fixture_dir(public_jwk=public_jwk, issuer=issuer, tmp_dir=tmp_path)
    env = compose_env(
        fixture_dir=fixture_dir,
        evidence_dir=evidence_dir,
        state_dir=state_dir,
        tenant_id=tenant_id,
        audience=audience,
        scope="AgentA.Access",
        authorized_client=authorized_client,
    )

    try:
        run_compose("up", "-d", "--build", env=env)
        wait_for_http("http://localhost:8080/agent-a/health")

        valid_token = build_token(
            private_key,
            tenant_id=tenant_id,
            audience=audience,
            scope="AgentA.Access",
            issuer=issuer,
            authorized_client=authorized_client,
        )
        status, body = request_json("http://localhost:8080/agent-a", token=valid_token, correlation_id="corr-valid")
        assert status == 200
        assert body["status"] == "PASS"
        assert body["upstream"]["service"] == "mock-agent-a"
        assert body["validation"]["signature_verified"] is True

        wrong_audience_token = build_token(
            private_key,
            tenant_id=tenant_id,
            audience="api://agent-b-example",
            scope="AgentA.Access",
            issuer=issuer,
            authorized_client=authorized_client,
        )
        status, body = request_json("http://localhost:8080/agent-a", token=wrong_audience_token, correlation_id="corr-wrong-aud")
        assert status in {401, 403}
        assert body["status"] == "FAIL"
        assert body["error_category"] == "INVALID_AUDIENCE"

        wrong_tenant_token = build_token(
            private_key,
            tenant_id="99999999-8888-7777-6666-555555444444",
            audience=audience,
            scope="AgentA.Access",
            issuer=issuer,
            authorized_client=authorized_client,
        )
        status, body = request_json("http://localhost:8080/agent-a", token=wrong_tenant_token, correlation_id="corr-wrong-tenant")
        assert status in {401, 403}
        assert body["status"] == "FAIL"
        assert body["error_category"] == "TENANT_MISMATCH"

        wrong_scope_token = build_token(
            private_key,
            tenant_id=tenant_id,
            audience=audience,
            scope="Wrong.Scope",
            issuer=issuer,
            authorized_client=authorized_client,
        )
        status, body = request_json("http://localhost:8080/agent-a", token=wrong_scope_token, correlation_id="corr-wrong-scope")
        assert status in {401, 403}
        assert body["status"] == "FAIL"
        assert body["error_category"] == "MISSING_SCOPE"

        wrong_client_token = build_token(
            private_key,
            tenant_id=tenant_id,
            audience=audience,
            scope="AgentA.Access",
            issuer=issuer,
            authorized_client="wrong-client",
        )
        status, body = request_json("http://localhost:8080/agent-a", token=wrong_client_token, correlation_id="corr-wrong-client")
        assert status in {401, 403}
        assert body["status"] == "FAIL"
        assert body["error_category"] == "UNAUTHORIZED_CLIENT"

        tampered_token = valid_token[:-1] + ("A" if valid_token[-1] != "A" else "B")
        status, body = request_json("http://localhost:8080/agent-a", token=tampered_token, correlation_id="corr-tampered")
        assert status in {401, 403}
        assert body["status"] == "FAIL"
        assert body["error_category"] in {"INVALID_SIGNATURE", "MALFORMED_TOKEN"}

        status, body = request_json("http://localhost:8080/agent-a", token=None, correlation_id="corr-missing")
        assert status == 401
        assert body["error_category"] == "MISSING_TOKEN"

        status, body = request_json("http://localhost:8080/agent-a", token="not.a.jwt", correlation_id="corr-malformed")
        assert status == 401
        assert body["error_category"] == "MALFORMED_TOKEN"

        expired_token = build_token(
            private_key,
            tenant_id=tenant_id,
            audience=audience,
            scope="AgentA.Access",
            issuer=issuer,
            authorized_client=authorized_client,
            expired=True,
        )
        status, body = request_json("http://localhost:8080/agent-a", token=expired_token, correlation_id="corr-expired")
        assert status in {401, 403}
        assert body["status"] == "FAIL"
        assert body["error_category"] == "EXPIRED_TOKEN"

        state_file = state_dir / "agent-a-state.json"
        state = json.loads(state_file.read_text(encoding="utf-8"))
        assert state["received_count"] == 1

        run_compose("stop", "validation-proxy", env=env)
        proxy_down_failed = False
        try:
            failure_status, failure_body = request_json("http://localhost:8080/agent-a", token=valid_token, correlation_id="corr-proxy-down")
        except Exception:
            proxy_down_failed = True
        else:
            assert failure_status >= 500
            assert failure_body["status"] == "FAIL"
            proxy_down_failed = True
        assert proxy_down_failed is True

        state = json.loads(state_file.read_text(encoding="utf-8"))
        assert state["received_count"] == 1

        evidence_path = latest_evidence(evidence_dir)
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        assert valid_token not in json.dumps(evidence)
        assert evidence["source"] == "kong-external-authorizer-spike"
        assert evidence["status"] in {"PASS", "FAIL"}
    finally:
        run_compose("down", "-v", "--remove-orphans", env=env)
