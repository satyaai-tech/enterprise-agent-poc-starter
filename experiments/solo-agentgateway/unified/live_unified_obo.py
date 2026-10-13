#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import jwt
from typing import Any
from urllib import error, request
from urllib.parse import urlparse

import msal
from dotenv import load_dotenv

from agents.agent_b.mcp_client import _extract_mcp_text, _parse_mcp_payload
from agents.flow_logging import extract_raw_user_identity

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from tests.identity.entra_device_obo_spike import (
        extract_delegated_scope_name,
        fetch_openid_configuration,
        validate_token_for_policy,
    )
except ModuleNotFoundError:
    import importlib.util

    module_path = REPO_ROOT / "tests" / "identity" / "entra_device_obo_spike.py"
    spec = importlib.util.spec_from_file_location("entra_device_obo_spike", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load Entra helper module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    extract_delegated_scope_name = getattr(module, "extract_delegated_scope_name")
    fetch_openid_configuration = getattr(module, "fetch_openid_configuration")
    validate_token_for_policy = getattr(module, "validate_token_for_policy")

REQUIRED_ENV_KEYS = [
    "ENTRA_TENANT_ID",
    "ENTRA_NOTEBOOK_CLIENT_ID",
    "ENTRA_AGENT_A_CLIENT_ID",
    "ENTRA_AGENT_A_CLIENT_SECRET_FILE",
    "ENTRA_AGENT_A_SCOPE",
    "ENTRA_AGENT_A_EXPECTED_AUDIENCE",
    "ENTRA_AGENT_B_CLIENT_ID",
    "ENTRA_AGENT_B_SCOPE",
    "ENTRA_AGENT_B_EXPECTED_AUDIENCE",
    "ENTRA_AGENT_B_CLIENT_SECRET_FILE",
    "ENTRA_BANKING_SCOPE",
    "ENTRA_BANKING_EXPECTED_AUDIENCE",
]

COMPOSE_FILE = REPO_ROOT / "experiments" / "solo-agentgateway" / "unified" / "compose.yaml"
LIVE_COMPOSE_FILE = REPO_ROOT / "experiments" / "solo-agentgateway" / "unified" / "compose.live.yaml"


def _load_env_without_printing() -> None:
    env_path = REPO_ROOT / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path, override=False)
    else:
        raise RuntimeError("Missing .env. Live validation cannot proceed without the required Entra values.")


def _require_secret_file(path_value: str, *, variable_name: str) -> Path:
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        raise RuntimeError(f"{variable_name} must be an absolute path.")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise RuntimeError(f"{variable_name} is missing, unreadable, or not accessible.") from exc
    if resolved.is_relative_to(REPO_ROOT.resolve()):
        raise RuntimeError(f"{variable_name} must not be inside the repository.")
    if not os.access(resolved, os.R_OK):
        raise RuntimeError(f"{variable_name} is not readable.")
    if resolved.stat().st_size <= 0:
        raise RuntimeError(f"{variable_name} is empty.")
    return resolved


def _require_config() -> dict[str, str]:
    _load_env_without_printing()
    values: dict[str, str] = {}
    missing: list[str] = []
    for key in REQUIRED_ENV_KEYS:
        value = (os.getenv(key) or "").strip()
        if not value:
            missing.append(key)
        else:
            values[key] = value
    if missing:
        raise RuntimeError(f"Missing required unified Entra configuration: {', '.join(missing)}")

    mode = (os.getenv("AGENT_B_TOKEN_C_MODE") or "").strip().lower()
    if not mode:
        os.environ["AGENT_B_TOKEN_C_MODE"] = "obo"
    elif mode != "obo":
        raise RuntimeError("AGENT_B_TOKEN_C_MODE must be set to 'obo' for this live validation path.")

    _require_secret_file(values["ENTRA_AGENT_A_CLIENT_SECRET_FILE"], variable_name="ENTRA_AGENT_A_CLIENT_SECRET_FILE")
    _require_secret_file(values["ENTRA_AGENT_B_CLIENT_SECRET_FILE"], variable_name="ENTRA_AGENT_B_CLIENT_SECRET_FILE")
    return values


def _fetch_json(url: str, *, token: str | None = None, method: str = "GET", payload: dict[str, Any] | None = None) -> tuple[int, Any]:
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    req = request.Request(url, headers=headers, method=method, data=body)
    try:
        with request.urlopen(req, timeout=20) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return response.status, json.loads(raw) if raw else {}
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return exc.code, {"error": {"message": raw or str(exc)}}
    except (error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"Gateway request failed for {url}: {exc}") from exc


def _wait_for_ready(url: str, *, timeout_seconds: int = 90) -> None:
    deadline = __import__("time").monotonic() + timeout_seconds
    last_error: Exception | None = None
    while __import__("time").monotonic() < deadline:
        try:
            with request.urlopen(request.Request(url, method="GET"), timeout=5):
                return
        except Exception as exc:  # pragma: no cover - retry loop
            last_error = exc
            __import__("time").sleep(1)
    raise RuntimeError(f"Timed out waiting for {url}: {last_error}")


def _discover_protected_a2a_url(base_url: str) -> str:
    status, card = _fetch_json(f"{base_url}/.well-known/agent-card.json")
    if status != 200 or not isinstance(card, dict):
        raise RuntimeError("Agent Card discovery failed before live validation could proceed.")
    advertised = card.get("url")
    if not isinstance(advertised, str) or not advertised.strip():
        for field_name in ("supportedInterfaces", "supported_interfaces"):
            interfaces = card.get(field_name, [])
            if not isinstance(interfaces, list):
                continue
            for entry in interfaces:
                if not isinstance(entry, dict):
                    continue
                candidate = entry.get("url") or entry.get("rpc_url") or entry.get("uri")
                if isinstance(candidate, str) and candidate.strip():
                    advertised = candidate
                    break
            if isinstance(advertised, str) and advertised.strip():
                break
    if not isinstance(advertised, str) or not advertised.strip():
        raise RuntimeError("Agent Card does not advertise a protected A2A interface URL.")
    path = urlparse(advertised).path or "/"
    return f"{base_url}{path}"


def _fetch_device_token(tenant_id: str, client_id: str, scope: str) -> str:
    authority = f"https://login.microsoftonline.com/{tenant_id}"
    app = msal.PublicClientApplication(client_id=client_id, authority=authority)
    flow = app.initiate_device_flow(scopes=[scope])
    if "message" not in flow:
        raise RuntimeError("Device flow did not return a Microsoft sign-in message.")
    print(flow.get("message", ""))
    result = app.acquire_token_by_device_flow(flow)
    token = result.get("access_token") if isinstance(result, dict) else None
    if not isinstance(token, str) or not token.strip():
        raise RuntimeError("Device-code sign-in did not return an access token.")
    return token


def _acquire_obo_token(tenant_id: str, client_id: str, client_secret: str, user_assertion: str, scope: str) -> str:
    authority = f"https://login.microsoftonline.com/{tenant_id}"
    app = msal.ConfidentialClientApplication(client_id=client_id, client_credential=client_secret, authority=authority)
    result = app.acquire_token_on_behalf_of(user_assertion=user_assertion, scopes=[scope])
    token = result.get("access_token") if isinstance(result, dict) else None
    if not isinstance(token, str) or not token.strip():
        raise RuntimeError("OBO exchange did not return an access token.")
    return token


def _validate_token(config: dict[str, str], token: str, *, expected_scope: str, expected_audience: str, expected_client: str, name: str) -> dict[str, Any]:
    # Use the existing validation helper to keep the live guard aligned with the proven Entra policy checks.
    metadata = fetch_openid_configuration(config["ENTRA_TENANT_ID"], version="2.0", timeout=5)
    issuer = metadata.get("issuer")
    if not issuer:
        raise RuntimeError(f"No issuer was returned for {name}.")
    result = validate_token_for_policy(
        token,
        tenant_id=config["ENTRA_TENANT_ID"],
        expected_audience=expected_audience,
        expected_scope=expected_scope,
        expected_issuer=issuer,
        expected_authorized_client=expected_client,
        test_name=name,
    )
    if result.get("result") != "PASS":
        raise RuntimeError(f"{name} failed validation: {result}")
    return result


def _compose_live_runtime_env(config: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    live = dict(config or {})

    def _require(value_name: str, *, allow_env: bool = False) -> str:
        value = (live.get(value_name) if live else None)
        if value is None or not str(value).strip():
            if allow_env:
                value = env.get(value_name)
            if value is None or not str(value).strip():
                raise RuntimeError(f"Missing validated live Entra mapping: {value_name}")
        return str(value).strip()

    tenant_id = _require("ENTRA_TENANT_ID", allow_env=True)
    issuer = f"https://login.microsoftonline.com/{tenant_id}/v2.0"
    jwks_url = f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys"

    api_audience = _require("ENTRA_AGENT_A_EXPECTED_AUDIENCE")
    a2a_audience = _require("ENTRA_AGENT_B_EXPECTED_AUDIENCE")
    mcp_audience = _require("ENTRA_BANKING_EXPECTED_AUDIENCE")
    api_scope = extract_delegated_scope_name(_require("ENTRA_AGENT_A_SCOPE"))
    a2a_scope = extract_delegated_scope_name(_require("ENTRA_AGENT_B_SCOPE"))
    banking_scope = extract_delegated_scope_name(_require("ENTRA_BANKING_SCOPE"))
    api_client = _require("ENTRA_NOTEBOOK_CLIENT_ID")
    a2a_client = _require("ENTRA_AGENT_A_CLIENT_ID")
    mcp_client = _require("ENTRA_AGENT_B_CLIENT_ID")
    agent_a_secret_file = _require("ENTRA_AGENT_A_CLIENT_SECRET_FILE")
    agent_b_secret_file = _require("ENTRA_AGENT_B_CLIENT_SECRET_FILE")
    banking_user_oid = (live.get("BANKING_TEST_USER_OID") or env.get("BANKING_TEST_USER_OID") or "user-12345").strip() or "user-12345"

    env.update(
        {
            "TENANT_ID": tenant_id,
            "ISSUER": issuer,
            "JWKS_URL": jwks_url,
            "API_AUDIENCE": api_audience,
            "A2A_AUDIENCE": a2a_audience,
            "MCP_AUDIENCE": mcp_audience,
            "API_SCOPE": api_scope,
            "A2A_SCOPE": a2a_scope,
            "BANKING_SCOPE": banking_scope,
            "API_AUTHORIZED_CLIENT": api_client,
            "A2A_AUTHORIZED_CLIENT": a2a_client,
            "MCP_AUTHORIZED_CLIENT": mcp_client,
            "BANKING_TEST_USER_OID": banking_user_oid,
            "BANKING_ISSUER": issuer,
            "BANKING_AUDIENCE": mcp_audience,
            "BANKING_AUTHORIZED_CLIENT": mcp_client,
            "AGENT_B_TOKEN_C_MODE": "obo",
            "AGENT_A_TOKEN_B_MODE": "obo",
            "POC_LOG_RAW_USER_ID": env.get("POC_LOG_RAW_USER_ID", "false"),
            "AG_CONFIG_PATH": env.get("AG_CONFIG_PATH", "/tmp/solo-agentgateway-unified-live-config"),
            "API_HOST_PORT": env.get("API_HOST_PORT", "18080"),
            "A2A_HOST_PORT": env.get("A2A_HOST_PORT", "18081"),
            "MCP_HOST_PORT": env.get("MCP_HOST_PORT", "18082"),
            "COMPOSE_PROJECT_NAME": env.get("COMPOSE_PROJECT_NAME", "solo-unified-live"),
            "ENTRA_TENANT_ID": tenant_id,
            "ENTRA_AGENT_A_CLIENT_ID": a2a_client,
            "ENTRA_AGENT_A_CLIENT_SECRET_FILE": agent_a_secret_file,
            "ENTRA_AGENT_B_SCOPE": _require("ENTRA_AGENT_B_SCOPE"),
            "ENTRA_AGENT_B_CLIENT_ID": mcp_client,
            "ENTRA_BANKING_SCOPE": _require("ENTRA_BANKING_SCOPE"),
            "ENTRA_AGENT_B_CLIENT_SECRET_FILE": agent_b_secret_file,
        }
    )
    return env


def _start_live_stack(config: dict[str, str] | None = None) -> None:
    docker_bin = shutil.which("docker")
    if docker_bin is None:
        raise RuntimeError("Docker executable not found in PATH for the live unified validation runner.")

    env = _compose_live_runtime_env(config)
    config_dir = Path(env.get("AG_CONFIG_PATH", "/tmp/solo-agentgateway-unified-live-config"))
    if config_dir.suffix.lower() in {".yaml", ".yml"}:
        config_path = config_dir
    else:
        config_path = config_dir / "config.yaml"
    config_dir.mkdir(parents=True, exist_ok=True)

    env["AG_CONFIG_PATH"] = str(config_dir)
    render_cmd = [sys.executable, str(REPO_ROOT / "experiments" / "solo-agentgateway" / "unified" / "render_config.py")]
    render_result = subprocess.run(render_cmd, cwd=REPO_ROOT, env=env, capture_output=True, text=True)
    if render_result.returncode != 0:
        output = render_result.stderr.strip() or render_result.stdout.strip() or "unknown render error"
        raise RuntimeError(f"Failed to render unified agentgateway config: {output}")

    if not config_path.exists():
        raise RuntimeError(f"Rendered live config is missing: {config_path}")

    compose_file = LIVE_COMPOSE_FILE if LIVE_COMPOSE_FILE.exists() else COMPOSE_FILE
    up_cmd = [docker_bin, "compose", "-f", str(compose_file), "up", "-d", "--build", "--wait"]
    up_result = subprocess.run(up_cmd, cwd=REPO_ROOT, env=env, capture_output=True, text=True)
    if up_result.returncode != 0:
        output = up_result.stderr.strip() or up_result.stdout.strip() or "unknown compose error"
        raise RuntimeError(f"Failed to start the unified live stack: {output}")


def _stop_live_stack(config: dict[str, str] | None = None) -> None:
    docker_bin = shutil.which("docker")
    if docker_bin is None:
        return
    env = _compose_live_runtime_env(config)
    env["AG_CONFIG_PATH"] = str(Path(env.get("AG_CONFIG_PATH", "/tmp/solo-agentgateway-unified-live-config")))
    compose_file = LIVE_COMPOSE_FILE if LIVE_COMPOSE_FILE.exists() else COMPOSE_FILE
    result = subprocess.run([docker_bin, "compose", "-f", str(compose_file), "down", "-v", "--remove-orphans"], cwd=REPO_ROOT, env=env, capture_output=True, text=True)
    if result.returncode != 0:
        # Cleanup should be best effort and never hide the original failure.
        return


def _extract_user_oid(token: str) -> str:
    try:
        claims = jwt.decode(token, options={"verify_signature": False, "verify_aud": False, "verify_exp": False, "verify_iss": False})
    except Exception as exc:  # pragma: no cover - live-only operational path
        raise RuntimeError("Unable to decode Token A to extract a validated user object ID.") from exc
    oid = str(claims.get("oid") or claims.get("sub") or "").strip()
    if not oid:
        raise RuntimeError("Validated Token A did not include an object ID for account ownership checks.")
    return oid


def _call_mcp_summary(mcp_url: str, token_c: str, account_id: str) -> str:
    try:
        import httpx
    except Exception as exc:  # pragma: no cover - runtime dependency guard
        raise RuntimeError("httpx is required for the live MCP summary call.") from exc

    async def _run() -> str:
        async with httpx.AsyncClient(timeout=30.0) as client:
            headers = {
                "Authorization": f"Bearer {token_c}",
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2025-03-26",
            }
            init = {
                "jsonrpc": "2.0",
                "id": "init-live",
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "live-unified-obo", "version": "1.0.0"},
                },
            }
            init_resp = await client.post(mcp_url, json=init, headers=headers)
            init_resp.raise_for_status()
            init_body = _parse_mcp_payload(init_resp.text)
            if init_body.get("error") is not None:
                raise RuntimeError("MCP initialize failed.")
            init_result = init_body.get("result")
            if not isinstance(init_result, dict):
                raise RuntimeError("MCP initialize response is invalid.")
            session_id = init_resp.headers.get("Mcp-Session-Id") or init_resp.headers.get("mcp-session-id")
            if not session_id:
                raise RuntimeError("MCP initialize response is missing an MCP session id.")

            notification_payload = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
            notification_resp = await client.post(mcp_url, json=notification_payload, headers={**headers, "Mcp-Session-Id": session_id})
            if notification_resp.status_code >= 400:
                raise RuntimeError("MCP notifications/initialized failed.")

            tools_payload = {
                "jsonrpc": "2.0",
                "id": "tools-live",
                "method": "tools/list",
                "params": {},
            }
            tools_resp = await client.post(mcp_url, json=tools_payload, headers={**headers, "Mcp-Session-Id": session_id})
            tools_resp.raise_for_status()
            tools_body = _parse_mcp_payload(tools_resp.text)
            if tools_body.get("error") is not None:
                raise RuntimeError("MCP tools/list failed.")
            tools_result = tools_body.get("result")
            if not isinstance(tools_result, dict):
                raise RuntimeError("MCP tools/list response is invalid.")
            tool_names = [tool.get("name") for tool in tools_result.get("tools", []) if isinstance(tool, dict)]
            if "get_account_summary" not in tool_names:
                raise RuntimeError("MCP server did not expose get_account_summary.")

            call_payload = {
                "jsonrpc": "2.0",
                "id": "call-live",
                "method": "tools/call",
                "params": {"name": "get_account_summary", "arguments": {"account_id": account_id}},
            }
            call_resp = await client.post(mcp_url, json=call_payload, headers={**headers, "Mcp-Session-Id": session_id})
            call_resp.raise_for_status()
            call_body = _parse_mcp_payload(call_resp.text)
            if call_body.get("error") is not None:
                raise RuntimeError("MCP tool call failed.")

            summary_text = _extract_mcp_text(call_body.get("result"))
            if not summary_text:
                raise RuntimeError("MCP response did not include usable account data.")
            return summary_text

    return asyncio.run(_run())


def run_live_unified_validation() -> int:
    config = _require_config()
    agent_a_secret_file = _require_secret_file(
        config["ENTRA_AGENT_A_CLIENT_SECRET_FILE"], variable_name="ENTRA_AGENT_A_CLIENT_SECRET_FILE"
    )
    secret_file = _require_secret_file(
        config["ENTRA_AGENT_B_CLIENT_SECRET_FILE"], variable_name="ENTRA_AGENT_B_CLIENT_SECRET_FILE"
    )
    agent_a_client_secret = agent_a_secret_file.read_text(encoding="utf-8").strip()
    client_secret = secret_file.read_text(encoding="utf-8").strip()
    if not agent_a_client_secret or not client_secret:
        raise RuntimeError("A required Entra client secret file is empty.")

    token_a = _fetch_device_token(
        config["ENTRA_TENANT_ID"],
        config["ENTRA_NOTEBOOK_CLIENT_ID"],
        config["ENTRA_AGENT_A_SCOPE"],
    )
    expected_agent_a_scope = extract_delegated_scope_name(config["ENTRA_AGENT_A_SCOPE"])
    _validate_token(
        config,
        token_a,
        expected_scope=expected_agent_a_scope,
        expected_audience=config["ENTRA_AGENT_A_EXPECTED_AUDIENCE"],
        expected_client=config["ENTRA_NOTEBOOK_CLIENT_ID"],
        name="agent_a_device_token",
    )
    banking_user_oid = _extract_user_oid(token_a)
    config = dict(config)
    config["BANKING_TEST_USER_OID"] = banking_user_oid

    started_stack = False
    try:
        _start_live_stack(config=config)
        started_stack = True

        if os.getenv("POC_LOG_RAW_USER_ID") == "true":
            print(json.dumps({"event": "token_a.identity.debug", **extract_raw_user_identity(token=token_a)}, separators=(",", ":")))

        token_b = _acquire_obo_token(
            config["ENTRA_TENANT_ID"],
            config["ENTRA_AGENT_A_CLIENT_ID"],
            agent_a_client_secret,
            user_assertion=token_a,
            scope=config["ENTRA_AGENT_B_SCOPE"],
        )
        expected_agent_b_scope = extract_delegated_scope_name(config["ENTRA_AGENT_B_SCOPE"])
        _validate_token(
            config,
            token_b,
            expected_scope=expected_agent_b_scope,
            expected_audience=config["ENTRA_AGENT_B_EXPECTED_AUDIENCE"],
            expected_client=config["ENTRA_AGENT_A_CLIENT_ID"],
            name="agent_b_obo_token",
        )
        if os.getenv("POC_LOG_RAW_USER_ID") == "true":
            print(json.dumps({"event": "token_b.identity.debug", **extract_raw_user_identity(token=token_b)}, separators=(",", ":")))

        a2a_base = f"http://127.0.0.1:{os.getenv('A2A_HOST_PORT', '18081')}"
        _wait_for_ready(f"{a2a_base}/.well-known/agent-card.json")
        protected_url = _discover_protected_a2a_url(a2a_base)
        status, body = _fetch_json(
            protected_url,
            token=token_b,
            method="POST",
            payload={
                "jsonrpc": "2.0",
                "method": "message/send",
                "params": {
                    "message": {
                        "messageId": "live-unified-obo",
                        "role": "user",
                        "parts": [{"kind": "text", "text": "Live unified Entra OBO validation"}],
                    }
                },
                "id": "live-unified-obo",
            },
        )
        if status != 200:
            raise RuntimeError(f"Unified A2A gateway rejected Token B: {status} {body}")

        token_c = _acquire_obo_token(
            config["ENTRA_TENANT_ID"],
            config["ENTRA_AGENT_B_CLIENT_ID"],
            client_secret,
            user_assertion=token_b,
            scope=config["ENTRA_BANKING_SCOPE"],
        )
        expected_banking_scope = extract_delegated_scope_name(config["ENTRA_BANKING_SCOPE"])
        _validate_token(
            config,
            token_c,
            expected_scope=expected_banking_scope,
            expected_audience=config["ENTRA_BANKING_EXPECTED_AUDIENCE"],
            expected_client=config["ENTRA_AGENT_B_CLIENT_ID"],
            name="banking_token_c",
        )
        if os.getenv("POC_LOG_RAW_USER_ID") == "true":
            print(json.dumps({"event": "token_c.identity.debug", **extract_raw_user_identity(token=token_c)}, separators=(",", ":")))

        mcp_url = f"http://127.0.0.1:{os.getenv('MCP_HOST_PORT', '18082')}/mcp"
        summary = _call_mcp_summary(mcp_url, token_c, "acct-1001")
        print("PHASE_5_LIVE_STATUS: PASS")
        print(f"PHASE_5_LIVE_RESULT: {summary}")
        return 0
    finally:
        if started_stack:
            _stop_live_stack(config=config)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Guarded live unified Entra OBO validation")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--live", action="store_true", help="Run the guarded live validation and clean up afterward.")
    action.add_argument("--start-only", action="store_true", help="Start the live stack and leave it running for Jupyter.")
    action.add_argument("--stop", action="store_true", help="Stop the persistent live stack.")
    args = parser.parse_args(argv)

    if not (args.live or args.start_only or args.stop):
        print("Safe mode only: pass --live, --start-only, or --stop explicitly.")
        return 0

    try:
        if args.start_only:
            config = _require_config()
            if not (os.getenv("BANKING_TEST_USER_OID") or "").strip():
                raise RuntimeError("BANKING_TEST_USER_OID must be set for the persistent notebook stack.")
            config = dict(config)
            config["BANKING_TEST_USER_OID"] = os.environ["BANKING_TEST_USER_OID"].strip()
            _start_live_stack(config=config)
            print("PHASE_5_STACK_STATUS: RUNNING")
            print(f"PHASE_5_STACK_API: http://127.0.0.1:{os.getenv('API_HOST_PORT', '18080')}")
            return 0
        if args.stop:
            _stop_live_stack(config=_require_config())
            print("PHASE_5_STACK_STATUS: STOPPED")
            return 0
        return run_live_unified_validation()
    except Exception as exc:  # pragma: no cover - live-only operational path
        print("PHASE_5_LIVE_STATUS: FAIL")
        print(f"PHASE_5_LIVE_ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
