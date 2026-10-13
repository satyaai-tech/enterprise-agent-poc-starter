from __future__ import annotations

import json
from pathlib import Path

import jwt
import pytest
import yaml
from cryptography.hazmat.primitives.asymmetric import rsa

from agents.agent_a.a2a_client import _protected_a2a_headers, _public_a2a_headers
from agents.token_provider import FileTokenProvider


def _build_token(private_key, *, issuer: str, audience: str, scope: str, authorized_client: str, tenant_id: str = "11111111-2222-3333-4444-555555666666") -> str:
    now = 1_700_000_000
    payload = {
        "iss": issuer,
        "aud": audience,
        "tid": tenant_id,
        "scp": scope,
        "sub": "user-12345",
        "oid": "user-12345",
        "iat": now - 60,
        "nbf": now - 30,
        "exp": now + 300,
        "ver": "2.0",
        "azp": authorized_client,
    }
    return jwt.encode(payload, private_key, algorithm="RS256", headers={"kid": "synthetic-kid"})


def _write_jwk_keypair(tmp_path: Path) -> tuple[rsa.RSAPrivateKey, Path]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    public_jwk["kid"] = "synthetic-kid"
    jwks_dir = tmp_path / "jwks"
    jwks_dir.mkdir(parents=True, exist_ok=True)
    (jwks_dir / "jwks.json").write_text(json.dumps({"keys": [public_jwk]}, indent=2), encoding="utf-8")
    return private_key, jwks_dir


def test_file_token_provider_rejects_missing_file(monkeypatch):
    monkeypatch.delenv("TOKEN_B_FILE", raising=False)
    with pytest.raises(RuntimeError, match="Missing required environment variable: TOKEN_B_FILE"):
        FileTokenProvider.from_env("TOKEN_B_FILE")


def test_file_token_provider_rejects_empty_file(tmp_path, monkeypatch):
    token_file = tmp_path / "token.txt"
    token_file.write_text("   \n\t  ", encoding="utf-8")
    monkeypatch.setenv("TOKEN_B_FILE", str(token_file))
    with pytest.raises(RuntimeError, match="Token file empty"):
        FileTokenProvider.from_env("TOKEN_B_FILE")


def test_agent_a_reads_only_token_b_file(tmp_path, monkeypatch):
    token_file = tmp_path / "token-b.txt"
    token_file.write_text("token-b-value\n", encoding="utf-8")
    monkeypatch.setenv("TOKEN_B_FILE", str(token_file))
    monkeypatch.delenv("TOKEN_A_FILE", raising=False)
    monkeypatch.delenv("TOKEN_C_FILE", raising=False)

    headers = _protected_a2a_headers()
    assert headers["Authorization"] == "Bearer token-b-value"
    assert "Authorization" in headers


def test_agent_b_reads_only_token_c_file(tmp_path, monkeypatch):
    token_file = tmp_path / "token-c.txt"
    token_file.write_text("token-c-value\n", encoding="utf-8")
    monkeypatch.setenv("TOKEN_C_FILE", str(token_file))
    monkeypatch.delenv("TOKEN_A_FILE", raising=False)
    monkeypatch.delenv("TOKEN_B_FILE", raising=False)

    provider = FileTokenProvider.from_env("TOKEN_C_FILE")
    assert provider.token == "token-c-value"
    assert "token-c-value" in provider.get_token()


def test_token_c_contains_banking_read_and_not_write(tmp_path):
    private_key, _ = _write_jwk_keypair(tmp_path)
    issuer = "https://login.microsoftonline.com/11111111-2222-3333-4444-555555666666/v2.0"
    token_c = _build_token(
        private_key,
        issuer=issuer,
        audience="api://banking-mock",
        scope="Banking.Read",
        authorized_client="synthetic-agent-b",
    )
    payload = jwt.decode(token_c, options={"verify_signature": False})
    assert payload["scp"] == "Banking.Read"
    assert "Banking.Write" not in payload["scp"]


def test_agent_card_discovery_does_not_include_authorization(monkeypatch):
    monkeypatch.setenv("TOKEN_B_FILE", "/tmp/does-not-matter")
    headers = _public_a2a_headers()
    assert "Authorization" not in headers
    assert "X-Flow-ID" in headers


def test_compose_adds_only_required_token_mounts():
    compose_path = Path(__file__).resolve().parents[2] / "experiments" / "solo-agentgateway" / "unified" / "compose.yaml"
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))

    agent_a = compose["services"]["agent-a"]
    agent_b = compose["services"]["agent-b"]

    assert agent_a["environment"]["TOKEN_B_FILE"] == "/run/secrets/token_b"
    assert agent_b["environment"]["TOKEN_C_FILE"] == "/run/secrets/token_c"
    assert "TOKEN_A_FILE" not in agent_a["environment"]
    assert "TOKEN_C_FILE" not in agent_a["environment"]
    assert "TOKEN_A_FILE" not in agent_b["environment"]
    assert "TOKEN_B_FILE" not in agent_b["environment"]

    a_mounts = agent_a["volumes"]
    b_mounts = agent_b["volumes"]
    assert any("/run/secrets/token_b:ro" in mount for mount in a_mounts)
    assert any("/run/secrets/token_c:ro" in mount for mount in b_mounts)
    assert all("/run/secrets/token_b:ro" not in mount for mount in b_mounts)
    assert all("/run/secrets/token_c:ro" not in mount for mount in a_mounts)
    assert "private_key" not in compose_path.read_text(encoding="utf-8").lower()


__all__ = [
    "test_file_token_provider_rejects_missing_file",
    "test_file_token_provider_rejects_empty_file",
    "test_agent_a_reads_only_token_b_file",
    "test_agent_b_reads_only_token_c_file",
    "test_token_c_contains_banking_read_and_not_write",
    "test_agent_card_discovery_does_not_include_authorization",
    "test_compose_adds_only_required_token_mounts",
]
