from __future__ import annotations

import importlib.util
from pathlib import Path

import jwt
import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = REPO_ROOT / "experiments" / "solo-agentgateway" / "unified" / "live_slice5c_two_user.py"


def _runner():
    spec = importlib.util.spec_from_file_location("live_slice5c_two_user", RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _token(*, tid: str, oid: str) -> str:
    return jwt.encode(
        {"tid": tid, "oid": oid},
        "test-only-secret-that-is-longer-than-thirty-two-bytes",
        algorithm="HS256",
    )


def test_slice5c_runner_is_safe_by_default(capsys) -> None:
    runner = _runner()

    assert runner.main([]) == 0
    assert "Safe mode only" in capsys.readouterr().out


def test_slice5c_identity_chain_requires_same_tid_and_oid() -> None:
    runner = _runner()
    token = _token(tid="tenant-1", oid="reader-1")

    assert runner._validate_identity_chain(token, token, token) == ("tenant-1", "reader-1")
    with pytest.raises(RuntimeError, match="same delegated user"):
        runner._validate_identity_chain(token, token, _token(tid="tenant-1", oid="writer-1"))


def test_slice5c_requires_both_delegated_banking_scopes() -> None:
    runner = _runner()

    assert runner._banking_scopes(
        {"ENTRA_BANKING_SCOPES": "api://banking/Banking.Read api://banking/Banking.Write"}
    ) == ["api://banking/Banking.Read", "api://banking/Banking.Write"]
    with pytest.raises(RuntimeError, match="both Banking.Read and Banking.Write"):
        runner._banking_scopes({"ENTRA_BANKING_SCOPES": "api://banking/Banking.Read"})


def test_slice5c_identity_evidence_is_pseudonymous() -> None:
    runner = _runner()
    reference = runner._identity_ref("tenant-1", "reader-1")

    assert len(reference) == 16
    assert "tenant-1" not in reference
    assert "reader-1" not in reference


def test_slice5c_live_runner_contains_required_denied_write_gates() -> None:
    source = RUNNER_PATH.read_text(encoding="utf-8")

    for label in (
        "Reader transfer",
        "Conflicting idempotency replay",
        "Unconfirmed transfer",
        "Transfer without idempotency key",
        "Non-positive transfer",
        "Cross-user transfer",
        "Reader cross-user read",
        "Writer cross-user read",
    ):
        assert label in source
    assert 'metrics.get("transfer_mutations_total") != 1' in source
    assert 'metrics.get("transfer_count") != 1' in source


def test_obo_failure_reports_entra_error_code_without_secrets(monkeypatch) -> None:
    live = _runner().live

    class _App:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def acquire_token_on_behalf_of(self, **kwargs):
            return {
                "error": "invalid_grant",
                "error_description": "AADSTS65001: consent required. Trace ID: abc\nCorrelation ID: def",
            }

    monkeypatch.setattr(live.msal, "ConfidentialClientApplication", _App)

    with pytest.raises(RuntimeError) as excinfo:
        live._acquire_obo_token("tenant", "client", "super-secret", user_assertion="assertion", scopes=["s"])

    message = str(excinfo.value)
    assert "invalid_grant" in message and "AADSTS65001: consent required" in message
    assert "super-secret" not in message and "assertion" not in message and "Trace ID" not in message



_JWT_KEY = "test-only-secret-that-is-longer-than-thirty-two-bytes"
_CONFIG = {
    "ENTRA_TENANT_ID": "tenant",
    "ENTRA_AGENT_A_CLIENT_ID": "agent-a",
    "ENTRA_AGENT_B_CLIENT_ID": "agent-b",
    "ENTRA_AGENT_B_SCOPE": "api://agent-b/AgentB.Access",
    "ENTRA_AGENT_B_EXPECTED_AUDIENCE": "agent-b",
    "ENTRA_BANKING_EXPECTED_AUDIENCE": "banking",
    "ENTRA_BANKING_SCOPES": "api://banking/Banking.Read api://banking/Banking.Write",
}


def _run_chain(monkeypatch, *, token_c_scp: str, required: set[str]):
    runner = _runner()
    calls: list[dict] = []
    validated: list[tuple[str, str]] = []

    def fake_obo(tenant, client, secret, *, user_assertion, scopes):
        calls.append({"client": client, "scopes": list(scopes)})
        scp = token_c_scp if len(calls) == 2 else "AgentB.Access"
        return jwt.encode({"scp": scp, "oid": "user-oid"}, _JWT_KEY, algorithm="HS256")

    monkeypatch.setattr(runner.live, "_acquire_obo_token", fake_obo)
    monkeypatch.setattr(
        runner.live,
        "_validate_token",
        lambda config, token, *, expected_scope, expected_client, **kwargs: validated.append((expected_scope, expected_client)),
    )
    runner._obo_chain(
        _CONFIG, "token-a", agent_a_secret="a-secret", agent_b_secret="b-secret", required_token_c_scopes=required
    )
    return calls, validated


def test_slice5c_reader_token_c_with_only_read_passes_and_requests_default_scope(monkeypatch) -> None:
    calls, validated = _run_chain(monkeypatch, token_c_scp="Banking.Read", required={"Banking.Read"})

    assert calls[1] == {"client": "agent-b", "scopes": ["api://banking/.default"]}
    assert ("Banking.Read", "agent-b") in validated
    assert all(scope != "Banking.Write" for scope, _ in validated)


def test_slice5c_reader_token_c_may_contain_write_scope(monkeypatch) -> None:
    _, validated = _run_chain(monkeypatch, token_c_scp="Banking.Read Banking.Write", required={"Banking.Read"})

    assert [scope for scope, _ in validated if scope.startswith("Banking")] == ["Banking.Read"]


def test_slice5c_writer_token_c_with_both_scopes_passes_and_validates_client(monkeypatch) -> None:
    calls, validated = _run_chain(
        monkeypatch, token_c_scp="Banking.Read Banking.Write", required={"Banking.Read", "Banking.Write"}
    )

    assert calls[1]["scopes"] == ["api://banking/.default"]
    assert sorted(item for item in validated if item[0].startswith("Banking")) == [
        ("Banking.Read", "agent-b"),
        ("Banking.Write", "agent-b"),
    ]


def test_slice5c_writer_token_c_missing_write_fails_closed_with_sanitized_error(monkeypatch) -> None:
    with pytest.raises(RuntimeError) as excinfo:
        _run_chain(monkeypatch, token_c_scp="Banking.Read", required={"Banking.Read", "Banking.Write"})

    message = str(excinfo.value)
    assert "Banking.Write" in message and "granted scope(s): Banking.Read" in message
    assert "user-oid" not in message and "tenant" not in message.replace("Token C", "")


def test_slice5c_required_scopes_must_be_configured(monkeypatch) -> None:
    with pytest.raises(RuntimeError, match="subset of the configured"):
        _run_chain(monkeypatch, token_c_scp="Banking.Read", required={"Banking.Admin"})


def test_slice5c_role_checks_remain_per_identity() -> None:
    source = RUNNER_PATH.read_text(encoding="utf-8")

    assert 'live._require_token_roles(reader_c, required={"Banking.Reader"}, forbidden={"Banking.Writer"})' in source
    assert 'live._require_token_roles(writer_c, required={"Banking.Reader", "Banking.Writer"})' in source
    assert 'required_token_c_scopes={"Banking.Read"},' in source
    assert 'required_token_c_scopes={"Banking.Read", "Banking.Write"},' in source


def test_slice5c_mixed_banking_resources_fail_closed() -> None:
    runner = _runner()

    with pytest.raises(Exception):
        runner.derive_banking_default_scope(["api://a/Banking.Read", "api://b/Banking.Write"])
