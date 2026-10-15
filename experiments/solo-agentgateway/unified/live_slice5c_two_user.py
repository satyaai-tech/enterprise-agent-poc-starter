#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

import httpx
import jwt


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agents.agent_b.mcp_client import _extract_mcp_text, _parse_mcp_payload
from agents.agent_b.token_c_provider import derive_banking_default_scope

_LIVE_RUNNER_PATH = Path(__file__).with_name("live_unified_obo.py")
_LIVE_RUNNER_SPEC = importlib.util.spec_from_file_location("live_unified_obo", _LIVE_RUNNER_PATH)
if _LIVE_RUNNER_SPEC is None or _LIVE_RUNNER_SPEC.loader is None:
    raise RuntimeError(f"Unable to load the live unified runner from {_LIVE_RUNNER_PATH}")
live = importlib.util.module_from_spec(_LIVE_RUNNER_SPEC)
_LIVE_RUNNER_SPEC.loader.exec_module(live)


def _claims(token: str) -> dict[str, Any]:
    try:
        claims = jwt.decode(
            token,
            options={"verify_signature": False, "verify_aud": False, "verify_exp": False, "verify_iss": False},
        )
    except Exception as exc:  # pragma: no cover - guarded live path
        raise RuntimeError("Unable to inspect a token after validation.") from exc
    if not isinstance(claims, dict):
        raise RuntimeError("Validated token claims were not an object.")
    return claims


def _identity(token: str) -> tuple[str, str]:
    claims = _claims(token)
    oid = str(claims.get("oid") or "").strip()
    tid = str(claims.get("tid") or "").strip()
    if not oid or not tid:
        raise RuntimeError("Validated token is missing tid or oid.")
    return tid, oid


def _identity_ref(tid: str, oid: str) -> str:
    return hashlib.sha256(f"{tid}:{oid}".encode("utf-8")).hexdigest()[:16]


def _validate_identity_chain(token_a: str, token_b: str, token_c: str) -> tuple[str, str]:
    identities = {_identity(token) for token in (token_a, token_b, token_c)}
    if len(identities) != 1:
        raise RuntimeError("Token A, Token B, and Token C did not preserve the same delegated user.")
    return next(iter(identities))


def _banking_scopes(config: dict[str, str]) -> list[str]:
    values = list(
        dict.fromkeys(
            part
            for chunk in config["ENTRA_BANKING_SCOPES"].split(",")
            for part in chunk.split()
            if part
        )
    )
    names = {live.extract_delegated_scope_name(scope) for scope in values}
    required = {"Banking.Read", "Banking.Write"}
    if not required.issubset(names):
        raise RuntimeError("ENTRA_BANKING_SCOPES must include both Banking.Read and Banking.Write for Slice 5C.")
    return values


def _labeled_obo(hop: str, *args: Any, **kwargs: Any) -> str:
    try:
        return live._acquire_obo_token(*args, **kwargs)
    except RuntimeError as exc:
        raise RuntimeError(f"{hop}: {exc}") from None


def _require_token_c_scopes(token_c: str, required: set[str]) -> None:
    granted = set(str(_claims(token_c).get("scp") or "").split())
    missing = required - granted
    if missing:
        raise RuntimeError(
            f"Token C is missing delegated scope(s): {', '.join(sorted(missing))}; "
            f"granted scope(s): {', '.join(sorted(granted)) or 'none'}."
        )


def _obo_chain(
    config: dict[str, str],
    token_a: str,
    *,
    agent_a_secret: str,
    agent_b_secret: str,
    required_token_c_scopes: set[str],
) -> tuple[str, str]:
    token_b = _labeled_obo(
        "Token B (Agent A -> Agent B)",
        config["ENTRA_TENANT_ID"],
        config["ENTRA_AGENT_A_CLIENT_ID"],
        agent_a_secret,
        user_assertion=token_a,
        scopes=[config["ENTRA_AGENT_B_SCOPE"]],
    )
    live._validate_token(
        config,
        token_b,
        expected_scope=live.extract_delegated_scope_name(config["ENTRA_AGENT_B_SCOPE"]),
        expected_audience=config["ENTRA_AGENT_B_EXPECTED_AUDIENCE"],
        expected_client=config["ENTRA_AGENT_A_CLIENT_ID"],
        name="slice5c_token_b",
    )
    scopes = _banking_scopes(config)
    token_c = _labeled_obo(
        "Token C (Agent B -> Banking)",
        config["ENTRA_TENANT_ID"],
        config["ENTRA_AGENT_B_CLIENT_ID"],
        agent_b_secret,
        user_assertion=token_b,
        scopes=[derive_banking_default_scope(scopes)],
    )
    configured = {live.extract_delegated_scope_name(scope) for scope in scopes}
    if not required_token_c_scopes or not required_token_c_scopes <= configured:
        raise RuntimeError("Required Token C scopes must be a non-empty subset of the configured Banking scopes.")
    _require_token_c_scopes(token_c, required_token_c_scopes)
    for scope in sorted(required_token_c_scopes):
        live._validate_token(
            config,
            token_c,
            expected_scope=scope,
            expected_audience=config["ENTRA_BANKING_EXPECTED_AUDIENCE"],
            expected_client=config["ENTRA_AGENT_B_CLIENT_ID"],
            name="slice5c_token_c",
        )
    return token_b, token_c


def _headers(token: str, *, session_id: str | None = None, idempotency_key: str | None = None) -> dict[str, str]:
    result = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": "2025-03-26",
        "X-Flow-ID": f"slice-5c-{uuid.uuid4().hex[:12]}",
    }
    if session_id:
        result["Mcp-Session-Id"] = session_id
    if idempotency_key:
        result["X-Idempotency-Key"] = idempotency_key
    return result


def _decode_response(response: httpx.Response) -> dict[str, Any]:
    try:
        return dict(_parse_mcp_payload(response.text))
    except ValueError:
        return {"error": {"message": "non-JSON denial response"}}


def _open_session(client: httpx.Client, mcp_url: str, token: str) -> tuple[str, set[str]]:
    headers = _headers(token)
    init = {
        "jsonrpc": "2.0",
        "id": "init-5c",
        "method": "initialize",
        "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "slice-5c-live", "version": "1.0"}},
    }
    response = client.post(mcp_url, json=init, headers=headers)
    response.raise_for_status()
    body = _decode_response(response)
    if body.get("error") is not None:
        raise RuntimeError("MCP initialize failed.")
    session_id = response.headers.get("Mcp-Session-Id") or response.headers.get("mcp-session-id")
    if not session_id:
        raise RuntimeError("MCP initialize did not return a session ID.")
    session_headers = _headers(token, session_id=session_id)
    notification = client.post(
        mcp_url,
        json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        headers=session_headers,
    )
    if notification.status_code >= 400:
        raise RuntimeError("MCP initialized notification failed.")
    listing = client.post(
        mcp_url,
        json={"jsonrpc": "2.0", "id": "tools-5c", "method": "tools/list", "params": {}},
        headers=session_headers,
    )
    listing.raise_for_status()
    listing_body = _decode_response(listing)
    result = listing_body.get("result")
    tools = result.get("tools") if isinstance(result, dict) else None
    if not isinstance(tools, list):
        raise RuntimeError("MCP tools/list returned an invalid result.")
    return session_id, {str(tool.get("name")) for tool in tools if isinstance(tool, dict)}


def _call_tool(
    client: httpx.Client,
    mcp_url: str,
    token: str,
    tool_name: str,
    arguments: dict[str, Any],
    *,
    idempotency_key: str | None = None,
) -> tuple[int, dict[str, Any]]:
    session_id, _ = _open_session(client, mcp_url, token)
    response = client.post(
        mcp_url,
        json={"jsonrpc": "2.0", "id": f"call-{uuid.uuid4().hex[:8]}", "method": "tools/call", "params": {"name": tool_name, "arguments": arguments}},
        headers=_headers(token, session_id=session_id, idempotency_key=idempotency_key),
    )
    return response.status_code, _decode_response(response)


def _result_text(body: dict[str, Any]) -> str:
    return _extract_mcp_text(body.get("result"))


def _compose_exec_json(config: dict[str, str], path: str) -> dict[str, Any]:
    docker = shutil.which("docker")
    if not docker:
        raise RuntimeError("Docker executable not found.")
    env = live._compose_live_runtime_env(config)
    command = [
        docker,
        "compose",
        "-f",
        str(live.LIVE_COMPOSE_FILE),
        "exec",
        "-T",
        "banking-mcp",
        "python",
        "-c",
        f"import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8080{path}').read().decode())",
    ]
    result = subprocess.run(command, cwd=REPO_ROOT, env=env, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError("Unable to read the private Banking MCP validation counters.")
    try:
        return json.loads(result.stdout.strip())
    except json.JSONDecodeError as exc:
        raise RuntimeError("Banking MCP returned invalid validation counters.") from exc


def _assert_denied(status: int, body: dict[str, Any], label: str) -> None:
    if status < 400 or body.get("error") is None:
        raise RuntimeError(f"{label} was not denied as required.")


def run_live_slice5c() -> int:
    config = live._require_config()
    _banking_scopes(config)
    agent_a_secret = live._require_secret_file(
        config["ENTRA_AGENT_A_CLIENT_SECRET_FILE"], variable_name="ENTRA_AGENT_A_CLIENT_SECRET_FILE"
    ).read_text(encoding="utf-8").strip()
    agent_b_secret = live._require_secret_file(
        config["ENTRA_AGENT_B_CLIENT_SECRET_FILE"], variable_name="ENTRA_AGENT_B_CLIENT_SECRET_FILE"
    ).read_text(encoding="utf-8").strip()

    print("SLICE_5C_LOGIN: Sign in with the POC Banking Reader identity.")
    reader_a = live._fetch_device_token(config["ENTRA_TENANT_ID"], config["ENTRA_NOTEBOOK_CLIENT_ID"], config["ENTRA_AGENT_A_SCOPE"])
    live._validate_token(
        config,
        reader_a,
        expected_scope=live.extract_delegated_scope_name(config["ENTRA_AGENT_A_SCOPE"]),
        expected_audience=config["ENTRA_AGENT_A_EXPECTED_AUDIENCE"],
        expected_client=config["ENTRA_NOTEBOOK_CLIENT_ID"],
        name="slice5c_reader_token_a",
    )
    reader_b, reader_c = _obo_chain(
        config,
        reader_a,
        agent_a_secret=agent_a_secret,
        agent_b_secret=agent_b_secret,
        required_token_c_scopes={"Banking.Read"},
    )
    reader_tid, reader_oid = _validate_identity_chain(reader_a, reader_b, reader_c)
    live._require_token_roles(reader_c, required={"Banking.Reader"}, forbidden={"Banking.Writer"})

    print("SLICE_5C_LOGIN: Sign in with the POC Banking Writer identity. Do not reuse the Reader account.")
    writer_a = live._fetch_device_token(config["ENTRA_TENANT_ID"], config["ENTRA_NOTEBOOK_CLIENT_ID"], config["ENTRA_AGENT_A_SCOPE"])
    live._validate_token(
        config,
        writer_a,
        expected_scope=live.extract_delegated_scope_name(config["ENTRA_AGENT_A_SCOPE"]),
        expected_audience=config["ENTRA_AGENT_A_EXPECTED_AUDIENCE"],
        expected_client=config["ENTRA_NOTEBOOK_CLIENT_ID"],
        name="slice5c_writer_token_a",
    )
    writer_b, writer_c = _obo_chain(
        config,
        writer_a,
        agent_a_secret=agent_a_secret,
        agent_b_secret=agent_b_secret,
        required_token_c_scopes={"Banking.Read", "Banking.Write"},
    )
    writer_tid, writer_oid = _validate_identity_chain(writer_a, writer_b, writer_c)
    live._require_token_roles(writer_c, required={"Banking.Reader", "Banking.Writer"})
    if reader_tid != writer_tid or reader_oid == writer_oid:
        raise RuntimeError("Reader and Writer must have distinct object IDs in the same tenant.")

    config = dict(config)
    config["BANKING_ACCOUNT_OWNERS_JSON"] = json.dumps(
        {
            "acct-9000": reader_oid,
            "acct-9001": reader_oid,
            "acct-1001": writer_oid,
            "acct-2002": writer_oid,
            "acct-3003": writer_oid,
        },
        separators=(",", ":"),
    )
    started = False
    try:
        live._start_live_stack(config=config)
        started = True
        _compose_exec_json(config, "/__debug/reset")
        mcp_url = f"http://127.0.0.1:{os.getenv('MCP_HOST_PORT', '18082')}/mcp"
        with httpx.Client(timeout=30.0) as client:
            _, reader_tools = _open_session(client, mcp_url, reader_c)
            if reader_tools != {"get_account_summary"}:
                raise RuntimeError("Reader tool discovery did not expose exactly the read tool.")
            read_status, read_body = _call_tool(client, mcp_url, reader_c, "get_account_summary", {"account_id": "acct-9000"})
            if read_status != 200 or not _result_text(read_body):
                raise RuntimeError("Reader could not read an owned account.")
            denied_status, denied_body = _call_tool(
                client,
                mcp_url,
                reader_c,
                "create_transfer",
                {"from_account": "acct-9000", "to_account": "acct-9001", "amount": 1.0, "confirmation": "yes"},
                idempotency_key="slice5c-reader-denied",
            )
            _assert_denied(denied_status, denied_body, "Reader transfer")
            cross_status, cross_body = _call_tool(client, mcp_url, reader_c, "get_account_summary", {"account_id": "acct-1001"})
            _assert_denied(cross_status, cross_body, "Reader cross-user read")

            _, writer_tools = _open_session(client, mcp_url, writer_c)
            if writer_tools != {"get_account_summary", "create_transfer"}:
                raise RuntimeError("Writer tool discovery did not expose the expected read and write tools.")
            writer_read_status, writer_read_body = _call_tool(client, mcp_url, writer_c, "get_account_summary", {"account_id": "acct-1001"})
            if writer_read_status != 200 or not _result_text(writer_read_body):
                raise RuntimeError("Writer could not read an owned account.")
            key = f"slice5c-writer-{uuid.uuid4().hex}"
            transfer_args = {"from_account": "acct-1001", "to_account": "acct-2002", "amount": 1.0, "confirmation": "yes"}
            first_status, first_body = _call_tool(client, mcp_url, writer_c, "create_transfer", transfer_args, idempotency_key=key)
            retry_status, retry_body = _call_tool(client, mcp_url, writer_c, "create_transfer", transfer_args, idempotency_key=key)
            if first_status != 200 or retry_status != 200 or _result_text(first_body) != _result_text(retry_body):
                raise RuntimeError("Writer transfer or idempotent replay failed.")
            conflict_status, conflict_body = _call_tool(
                client,
                mcp_url,
                writer_c,
                "create_transfer",
                {**transfer_args, "amount": 2.0},
                idempotency_key=key,
            )
            _assert_denied(conflict_status, conflict_body, "Conflicting idempotency replay")
            no_confirmation_status, no_confirmation_body = _call_tool(
                client,
                mcp_url,
                writer_c,
                "create_transfer",
                {**transfer_args, "confirmation": "no"},
                idempotency_key=f"slice5c-no-confirm-{uuid.uuid4().hex}",
            )
            _assert_denied(no_confirmation_status, no_confirmation_body, "Unconfirmed transfer")
            no_key_status, no_key_body = _call_tool(
                client,
                mcp_url,
                writer_c,
                "create_transfer",
                transfer_args,
            )
            _assert_denied(no_key_status, no_key_body, "Transfer without idempotency key")
            invalid_amount_status, invalid_amount_body = _call_tool(
                client,
                mcp_url,
                writer_c,
                "create_transfer",
                {**transfer_args, "amount": 0.0},
                idempotency_key=f"slice5c-invalid-amount-{uuid.uuid4().hex}",
            )
            _assert_denied(invalid_amount_status, invalid_amount_body, "Non-positive transfer")
            unowned_transfer_status, unowned_transfer_body = _call_tool(
                client,
                mcp_url,
                writer_c,
                "create_transfer",
                {"from_account": "acct-1001", "to_account": "acct-9000", "amount": 1.0, "confirmation": "yes"},
                idempotency_key=f"slice5c-unowned-{uuid.uuid4().hex}",
            )
            _assert_denied(unowned_transfer_status, unowned_transfer_body, "Cross-user transfer")
            writer_cross_status, writer_cross_body = _call_tool(
                client,
                mcp_url,
                writer_c,
                "get_account_summary",
                {"account_id": "acct-9000"},
            )
            _assert_denied(writer_cross_status, writer_cross_body, "Writer cross-user read")

        metrics = _compose_exec_json(config, "/__debug/metrics")
        if metrics.get("transfer_mutations_total") != 1 or metrics.get("transfer_count") != 1:
            raise RuntimeError("Slice 5C did not produce exactly one authorized transfer mutation.")
        print("PHASE_5_SLICE_5C_LIVE_STATUS: PASS")
        print(
            "PHASE_5_SLICE_5C_IDENTITIES: "
            + json.dumps(
                {
                    "reader_ref": _identity_ref(reader_tid, reader_oid),
                    "writer_ref": _identity_ref(writer_tid, writer_oid),
                    "same_tenant": True,
                    "distinct_users": True,
                },
                separators=(",", ":"),
            )
        )
        print(
            "PHASE_5_SLICE_5C_MUTATIONS: "
            + json.dumps(
                {
                    "transfer_mutations_total": metrics.get("transfer_mutations_total"),
                    "transfer_count": metrics.get("transfer_count"),
                    "idempotent_retries_total": metrics.get("idempotent_retries_total"),
                },
                separators=(",", ":"),
            )
        )
        return 0
    finally:
        if started:
            live._stop_live_stack(config=config)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Guarded Phase 5 Slice 5C two-user Entra validation")
    parser.add_argument("--live", action="store_true", help="Run two independent live sign-ins and clean up afterward.")
    args = parser.parse_args(argv)
    if not args.live:
        print("Safe mode only: pass --live explicitly to run the two-user validation.")
        return 0
    try:
        return run_live_slice5c()
    except Exception as exc:  # pragma: no cover - guarded live path
        print("PHASE_5_SLICE_5C_LIVE_STATUS: FAIL")
        print(f"PHASE_5_SLICE_5C_LIVE_ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
