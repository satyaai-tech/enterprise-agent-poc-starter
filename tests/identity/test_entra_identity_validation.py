from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

module_path = Path(__file__).with_name("entra_device_obo_spike.py")
spec = importlib.util.spec_from_file_location("entra_device_obo_spike", module_path)
assert spec is not None and spec.loader is not None
entra_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entra_module)

get_runtime_config = entra_module.get_runtime_config
metadata_url_for_version = entra_module.metadata_url_for_version
extract_delegated_scope_name = entra_module.extract_delegated_scope_name
resolve_expected_issuer = entra_module.resolve_expected_issuer
summarize_live_validation = entra_module.summarize_live_validation
validate_token_for_policy = entra_module.validate_token_for_policy
run_live_spike = entra_module.run_live_spike


def build_synthetic_rsa_jwk_pair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(public_key))
    return private_key, public_jwk


def build_signed_token(
    private_key,
    *,
    tenant_id: str,
    audience: str,
    scope: str,
    issuer: str,
    version: str = "2.0",
) -> str:
    now = int(datetime.now(timezone.utc).timestamp())
    payload = {
        "ver": version,
        "iss": issuer,
        "aud": audience,
        "tid": tenant_id,
        "scp": scope,
        "exp": now + 3600,
        "nbf": now - 60,
        "iat": now - 120,
    }
    return jwt.encode(payload, private_key, algorithm="RS256", headers={"kid": "synthetic-kid"})


def test_extract_delegated_scope_name_from_full_request_scope():
    assert extract_delegated_scope_name("api://agent-a-client-id/AgentA.Access") == "AgentA.Access"
    assert extract_delegated_scope_name("api://agent-b-client-id/AgentB.Access") == "AgentB.Access"

    with pytest.raises(ValueError, match=r"required|empty|malformed|\.default"):
        extract_delegated_scope_name("")
    with pytest.raises(ValueError, match=r"\.default"):
        extract_delegated_scope_name("api://agent-a-client-id/.default")


def test_metadata_urls_are_exact_for_v1_and_v2():
    assert metadata_url_for_version("tenant-123", "1.0") == "https://login.microsoftonline.com/tenant-123/.well-known/openid-configuration"
    assert metadata_url_for_version("tenant-123", "2.0") == "https://login.microsoftonline.com/tenant-123/v2.0/.well-known/openid-configuration"


def test_unknown_token_version_is_rejected():
    with pytest.raises(ValueError, match="Unsupported token version"):
        metadata_url_for_version("tenant-123", "3.0")


def test_v2_metadata_issuer_validation(monkeypatch):
    private_key, public_jwk = build_synthetic_rsa_jwk_pair()
    tenant_id = "11111111-2222-3333-4444-555555666666"
    audience = "api://agent-a-example"
    scope = "access_as_user"
    issuer = f"https://login.microsoftonline.com/{tenant_id}/v2.0"
    public_jwk["kid"] = "synthetic-kid"
    token = build_signed_token(private_key, tenant_id=tenant_id, audience=audience, scope=scope, issuer=issuer, version="2.0")

    monkeypatch.setattr(
        entra_module,
        "fetch_openid_configuration",
        lambda tenant_id, *, version, timeout=5: {"issuer": issuer, "jwks_uri": "https://example.test/jwks"},
    )
    monkeypatch.setattr(
        entra_module,
        "fetch_jwks_document",
        lambda jwks_uri, *, timeout=5: {"keys": [public_jwk]},
    )

    result = validate_token_for_policy(
        token,
        tenant_id=tenant_id,
        expected_audience=audience,
        expected_scope=scope,
        expected_issuer=issuer,
        test_name="synthetic_v2_issuer_check",
    )

    assert result["result"] == "PASS"
    assert result["issuer_verified"] is True
    assert result["tenant_verified"] is True


def test_full_request_scope_matches_short_scp_value(monkeypatch):
    private_key, public_jwk = build_synthetic_rsa_jwk_pair()
    tenant_id = "11111111-2222-3333-4444-555555666666"
    audience = "api://agent-a-example"
    short_scope = "AgentA.Access"
    full_scope = "api://agent-a-client-id/AgentA.Access"
    issuer = f"https://login.microsoftonline.com/{tenant_id}/v2.0"
    public_jwk["kid"] = "synthetic-kid"
    token = build_signed_token(private_key, tenant_id=tenant_id, audience=audience, scope=short_scope, issuer=issuer, version="2.0")

    monkeypatch.setattr(
        entra_module,
        "fetch_openid_configuration",
        lambda tenant_id, *, version, timeout=5: {"issuer": issuer, "jwks_uri": "https://example.test/jwks"},
    )
    monkeypatch.setattr(
        entra_module,
        "fetch_jwks_document",
        lambda jwks_uri, *, timeout=5: {"keys": [public_jwk]},
    )

    result = validate_token_for_policy(
        token,
        tenant_id=tenant_id,
        expected_audience=audience,
        expected_scope=full_scope,
        expected_issuer=issuer,
        test_name="synthetic_full_scope_match",
    )

    assert result["result"] == "PASS"
    assert result["scope_verified"] is True


def test_metadata_failure_maps_to_safe_metadata_error_category(monkeypatch):
    private_key, public_jwk = build_synthetic_rsa_jwk_pair()
    tenant_id = "11111111-2222-3333-4444-555555666666"
    audience = "api://agent-a-example"
    short_scope = "AgentA.Access"
    issuer = f"https://login.microsoftonline.com/{tenant_id}/v2.0"
    public_jwk["kid"] = "synthetic-kid"
    token = build_signed_token(private_key, tenant_id=tenant_id, audience=audience, scope=short_scope, issuer=issuer, version="2.0")

    monkeypatch.setattr(
        entra_module,
        "fetch_openid_configuration",
        lambda *args, **kwargs: (_ for _ in ()).throw(entra_module.MetadataError("Metadata request failed.")),
    )

    result = validate_token_for_policy(
        token,
        tenant_id=tenant_id,
        expected_audience=audience,
        expected_scope=short_scope,
        expected_issuer=issuer,
        test_name="synthetic_metadata_failure",
    )

    assert result["result"] == "FAIL"
    assert result["error_category"] == "METADATA_FAILURE"


def test_missing_config_fails_safely(monkeypatch):
    monkeypatch.delenv("ENTRA_TENANT_ID", raising=False)
    monkeypatch.delenv("ENTRA_NOTEBOOK_CLIENT_ID", raising=False)
    with pytest.raises(RuntimeError, match="Missing required Entra configuration"):
        get_runtime_config()


def test_valid_synthetic_token_passes_policy(monkeypatch):
    private_key, public_jwk = build_synthetic_rsa_jwk_pair()
    tenant_id = "11111111-2222-3333-4444-555555666666"
    audience = "api://agent-a-example"
    scope = "access_as_user"
    issuer = f"https://sts.windows.net/{tenant_id}/"
    token = build_signed_token(private_key, tenant_id=tenant_id, audience=audience, scope=scope, issuer=issuer)
    public_jwk["kid"] = "synthetic-kid"

    monkeypatch.setattr(
        entra_module,
        "fetch_openid_configuration",
        lambda tenant_id, *, version, timeout=5: {"issuer": issuer, "jwks_uri": "https://example.test/jwks"},
    )
    monkeypatch.setattr(
        entra_module,
        "fetch_jwks_document",
        lambda jwks_uri, *, timeout=5: {"keys": [public_jwk]},
    )

    result = validate_token_for_policy(
        token,
        tenant_id=tenant_id,
        expected_audience=audience,
        expected_scope=scope,
        expected_issuer=issuer,
        test_name="synthetic_valid_token",
    )

    assert result["result"] == "PASS"
    assert result["signature_verified"] is True
    assert result["issuer_verified"] is True
    assert result["tenant_verified"] is True
    assert result["audience_verified"] is True
    assert result["lifetime_verified"] is True
    assert result["scope_verified"] is True
    assert result["token_version"] == "2.0"
    assert len(result["token_fingerprint"]) == 64
    assert "api://agent-a-example" not in json.dumps(result)
    assert "11111111" not in json.dumps(result)
    assert "oid" not in json.dumps(result).lower()
    assert "sub" not in json.dumps(result).lower()


def test_modified_signature_is_rejected(monkeypatch):
    private_key, public_jwk = build_synthetic_rsa_jwk_pair()
    tenant_id = "11111111-2222-3333-4444-555555666666"
    audience = "api://agent-a-example"
    scope = "access_as_user"
    issuer = f"https://sts.windows.net/{tenant_id}/"
    token = build_signed_token(private_key, tenant_id=tenant_id, audience=audience, scope=scope, issuer=issuer)
    public_jwk["kid"] = "synthetic-kid"
    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")

    monkeypatch.setattr(
        entra_module,
        "fetch_openid_configuration",
        lambda tenant_id, *, version, timeout=5: {"issuer": issuer, "jwks_uri": "https://example.test/jwks"},
    )
    monkeypatch.setattr(
        entra_module,
        "fetch_jwks_document",
        lambda jwks_uri, *, timeout=5: {"keys": [public_jwk]},
    )

    result = validate_token_for_policy(
        tampered,
        tenant_id=tenant_id,
        expected_audience=audience,
        expected_scope=scope,
        expected_issuer=issuer,
        test_name="synthetic_invalid_signature",
    )

    assert result["result"] == "FAIL"
    assert result["error_category"] == "INVALID_SIGNATURE"
    assert result["signature_verified"] is False


def test_wrong_audience_and_missing_scope_are_rejected(monkeypatch):
    private_key, public_jwk = build_synthetic_rsa_jwk_pair()
    tenant_id = "11111111-2222-3333-4444-555555666666"
    audience = "api://agent-a-example"
    wrong_audience = "api://agent-b-example"
    scope = "access_as_user"
    issuer = f"https://sts.windows.net/{tenant_id}/"
    public_jwk["kid"] = "synthetic-kid"

    monkeypatch.setattr(
        entra_module,
        "fetch_openid_configuration",
        lambda tenant_id, *, version, timeout=5: {"issuer": issuer, "jwks_uri": "https://example.test/jwks"},
    )
    monkeypatch.setattr(
        entra_module,
        "fetch_jwks_document",
        lambda jwks_uri, *, timeout=5: {"keys": [public_jwk]},
    )

    token = build_signed_token(private_key, tenant_id=tenant_id, audience=audience, scope=scope, issuer=issuer)
    wrong_audience_result = validate_token_for_policy(
        token,
        tenant_id=tenant_id,
        expected_audience=wrong_audience,
        expected_scope=scope,
        expected_issuer=issuer,
        test_name="synthetic_wrong_audience",
    )
    assert wrong_audience_result["result"] == "FAIL"
    assert wrong_audience_result["error_category"] == "INVALID_AUDIENCE"
    assert wrong_audience_result["audience_verified"] is False

    payload_without_scope = {
        "ver": "2.0",
        "iss": issuer,
        "aud": audience,
        "tid": tenant_id,
        "exp": int(datetime.now(timezone.utc).timestamp()) + 3600,
        "nbf": int(datetime.now(timezone.utc).timestamp()) - 60,
        "iat": int(datetime.now(timezone.utc).timestamp()) - 120,
    }
    token_without_scope = jwt.encode(payload_without_scope, private_key, algorithm="RS256", headers={"kid": "synthetic-kid"})
    missing_scope_result = validate_token_for_policy(
        token_without_scope,
        tenant_id=tenant_id,
        expected_audience=audience,
        expected_scope=scope,
        expected_issuer=issuer,
        test_name="synthetic_missing_scope",
    )
    assert missing_scope_result["result"] == "FAIL"
    assert missing_scope_result["error_category"] == "MISSING_SCOPE"
    assert missing_scope_result["scope_verified"] is False


def test_agent_a_token_as_agent_b_has_expected_negative_result(monkeypatch):
    private_key, public_jwk = build_synthetic_rsa_jwk_pair()
    tenant_id = "11111111-2222-3333-4444-555555666666"
    agent_a_audience = "api://agent-a-example"
    agent_b_audience = "api://agent-b-example"
    agent_a_scope = "access_as_user"
    agent_b_scope = "access_as_b_user"
    issuer = f"https://login.microsoftonline.com/{tenant_id}/v2.0"
    public_jwk["kid"] = "synthetic-kid"
    token = build_signed_token(
        private_key,
        tenant_id=tenant_id,
        audience=agent_a_audience,
        scope=agent_a_scope,
        issuer=issuer,
        version="2.0",
    )

    monkeypatch.setattr(
        entra_module,
        "fetch_openid_configuration",
        lambda tenant_id, *, version, timeout=5: {"issuer": issuer, "jwks_uri": "https://example.test/jwks"},
    )
    monkeypatch.setattr(
        entra_module,
        "fetch_jwks_document",
        lambda jwks_uri, *, timeout=5: {"keys": [public_jwk]},
    )

    result = validate_token_for_policy(
        token,
        tenant_id=tenant_id,
        expected_audience=agent_b_audience,
        expected_scope=agent_b_scope,
        expected_issuer=issuer,
        test_name="agent_a_as_agent_b_negative",
    )

    assert result["result"] == "FAIL"
    assert result["error_category"] == "INVALID_AUDIENCE"
    assert result["audience_verified"] is False


def test_evidence_serialization_excludes_identifiers_and_sensitive_claims(monkeypatch):
    private_key, public_jwk = build_synthetic_rsa_jwk_pair()
    tenant_id = "11111111-2222-3333-4444-555555666666"
    audience = "api://agent-a-example"
    scope = "access_as_user"
    issuer = f"https://sts.windows.net/{tenant_id}/"
    public_jwk["kid"] = "synthetic-kid"
    monkeypatch.setattr(
        entra_module,
        "fetch_openid_configuration",
        lambda tenant_id, *, version, timeout=5: {"issuer": issuer, "jwks_uri": "https://example.test/jwks"},
    )
    monkeypatch.setattr(
        entra_module,
        "fetch_jwks_document",
        lambda jwks_uri, *, timeout=5: {"keys": [public_jwk]},
    )

    token = build_signed_token(private_key, tenant_id=tenant_id, audience=audience, scope=scope, issuer=issuer)
    result = validate_token_for_policy(
        token,
        tenant_id=tenant_id,
        expected_audience=audience,
        expected_scope=scope,
        expected_issuer=issuer,
        test_name="synthetic_evidence_redaction_check",
    )
    serialized = json.dumps(result, sort_keys=True)

    assert "11111111" not in serialized
    assert "api://agent-a-example" not in serialized
    assert "access_as_user" not in serialized
    assert "oid" not in serialized.lower()
    assert "sub" not in serialized.lower()
    assert "email" not in serialized.lower()
    assert "signature_verified" in serialized
    assert "scope_verified" in serialized


def test_run_live_spike_returns_nonzero_when_any_required_validation_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(
        entra_module,
        "_repo_root",
        lambda: tmp_path,
    )
    monkeypatch.setattr(
        entra_module,
        "get_runtime_config",
        lambda: {
            "ENTRA_TENANT_ID": "tenant-123",
            "ENTRA_NOTEBOOK_CLIENT_ID": "notebook",
            "ENTRA_AGENT_A_CLIENT_ID": "agent-a",
            "ENTRA_AGENT_A_CLIENT_SECRET": "secret",
            "ENTRA_AGENT_A_APPLICATION_ID_URI": "api://agent-a",
            "ENTRA_AGENT_A_SCOPE": "api://agent-a-client-id/AgentA.Access",
            "ENTRA_AGENT_A_EXPECTED_AUDIENCE": "api://agent-a",
            "ENTRA_AGENT_B_CLIENT_ID": "agent-b",
            "ENTRA_AGENT_B_APPLICATION_ID_URI": "api://agent-b",
            "ENTRA_AGENT_B_SCOPE": "api://agent-b-client-id/AgentB.Access",
            "ENTRA_AGENT_B_EXPECTED_AUDIENCE": "api://agent-b",
        },
    )

    class FakeApp:
        def __init__(self, *args, **kwargs):
            pass

        def initiate_device_flow(self, scopes):
            return {"message": "sign in"}

        def acquire_token_by_device_flow(self, flow):
            return {"access_token": "agent-a-token"}

    class FakeOboApp:
        def __init__(self, *args, **kwargs):
            pass

        def acquire_token_on_behalf_of(self, user_assertion, scopes):
            return {"access_token": "agent-b-token"}

    captured = {}

    def fake_write_evidence(result, *, destination):
        captured["destination"] = destination
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(result, sort_keys=True), encoding="utf-8")

    monkeypatch.setattr(entra_module.msal, "PublicClientApplication", lambda **kwargs: FakeApp())
    monkeypatch.setattr(entra_module.msal, "ConfidentialClientApplication", lambda **kwargs: FakeOboApp())
    monkeypatch.setattr(entra_module, "resolve_expected_issuer", lambda tenant_id, token: "https://login.microsoftonline.com/tenant-123/v2.0")
    monkeypatch.setattr(entra_module, "write_evidence", fake_write_evidence)

    def fake_validate(token, **kwargs):
        if kwargs["test_name"] == "agent_a_live_validation":
            return {"result": "PASS", "error_category": "NONE"}
        if kwargs["test_name"] == "agent_b_live_validation":
            return {"result": "FAIL", "error_category": "INVALID_AUDIENCE"}
        return {"result": "FAIL", "error_category": "INVALID_AUDIENCE", "audience_verified": False, "pass": False}

    monkeypatch.setattr(entra_module, "validate_token_for_policy", fake_validate)

    assert run_live_spike() == 1
    assert captured["destination"].resolve().is_relative_to(tmp_path.resolve())
    assert not captured["destination"].resolve().is_relative_to(Path(__file__).resolve().parents[2].resolve())


def test_summarize_live_validation_requires_all_positive_and_negative_checks():
    negative_pass = {
        "test_name": "agent_a_as_agent_b_negative",
        "expected_outcome": "FAIL",
        "actual_outcome": "FAIL",
        "error_category": "INVALID_AUDIENCE",
        "pass": True,
    }
    negative_fail = {**negative_pass, "pass": False}

    assert summarize_live_validation({"result": "PASS"}, {"result": "PASS"}, negative_pass) == "PASS"
    assert summarize_live_validation({"result": "PASS"}, {"result": "FAIL"}, negative_pass) == "FAIL"
    assert summarize_live_validation({"result": "PASS"}, {"result": "PASS"}, negative_fail) == "FAIL"
