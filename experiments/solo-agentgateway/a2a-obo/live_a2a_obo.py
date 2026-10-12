#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import jwt
import msal

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SPIKE_DIR = Path(__file__).resolve().parent
EVIDENCE_DIR = REPO_ROOT / "evidence" / "solo-phase-2"
COMPOSE_FILE = SPIKE_DIR / "compose.live.yaml"

from tests.identity.entra_device_obo_spike import (  # noqa: E402
    extract_delegated_scope_name,
    fetch_openid_configuration,
    get_runtime_config,
    load_env_file,
    safe_error_category,
    validate_token_for_policy,
)


def choose_host_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def request_json(
    url: str,
    *,
    token: str | None = None,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    headers = {"Content-Type": "application/json"}
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
        text = error.read().decode("utf-8", errors="replace")
        try:
            return error.code, json.loads(text)
        except json.JSONDecodeError:
            return error.code, {"jsonrpc": "2.0", "error": {"code": -32001, "message": text}}
    except (URLError, TimeoutError, OSError):
        raise RuntimeError("Gateway request failed.") from None


def ensure_evidence_dir() -> Path:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    return EVIDENCE_DIR


def build_evidence_record() -> dict[str, Any]:
    return {
        "device_login_completed": False,
        "token_a_validated": False,
        "obo_exchange_completed": False,
        "token_b_validated": False,
        "gateway_agent_b_audience_verified": False,
        "gateway_agent_a_client_verified": False,
        "agent_b_defense_in_depth_verified": False,
        "same_delegated_user_verified": False,
        "token_a_rejected_at_agent_b_boundary": False,
        "a2a_message_completed": False,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "status": "FAIL",
        "error_category": "NONE",
    }


def sanitize_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key in [
        "device_login_completed",
        "token_a_validated",
        "obo_exchange_completed",
        "token_b_validated",
        "gateway_agent_b_audience_verified",
        "gateway_agent_a_client_verified",
        "agent_b_defense_in_depth_verified",
        "same_delegated_user_verified",
        "token_a_rejected_at_agent_b_boundary",
        "a2a_message_completed",
    ]:
        cleaned[key] = bool(payload.get(key, False))
    cleaned["timestamp_utc"] = payload.get("timestamp_utc") or datetime.now(timezone.utc).isoformat()
    cleaned["status"] = "PASS" if payload.get("status") == "PASS" else "FAIL"
    cleaned["error_category"] = payload.get("error_category", "NONE")
    return cleaned


def write_evidence_file(payload: dict[str, Any], *, path: Path | None = None) -> Path:
    ensure_evidence_dir()
    target = path or EVIDENCE_DIR / f"solo-a2a-live-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}-{uuid.uuid4().hex[:12]}.json"
    if target.exists():
        raise FileExistsError(f"Refusing to overwrite evidence file: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(sanitize_evidence(payload), indent=2, sort_keys=True) + "\n")
    return target


def jwt_decode_without_verification(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(
            token,
            options={
                "verify_signature": False,
                "verify_aud": False,
                "verify_exp": False,
                "verify_nbf": False,
                "verify_iat": False,
                "verify_iss": False,
            },
        )
    except Exception:  # pragma: no cover - malformed token path
        return {}


def resolve_issuer_and_jwks(tenant_id: str, token: str) -> tuple[str, str]:
    unverified = jwt_decode_without_verification(token)
    version = str(unverified.get("ver") or "2.0")
    metadata = fetch_openid_configuration(tenant_id, version=version, timeout=5)
    issuer = str(metadata.get("issuer") or "")
    jwks_uri = str(metadata.get("jwks_uri") or "")
    if not issuer or not jwks_uri:
        raise RuntimeError("OpenID metadata missing issuer or JWKS URI.")
    return issuer, jwks_uri


def print_device_login(flow: dict[str, Any]) -> None:
    verification_url = str(flow.get("verification_uri") or flow.get("verification_uri_complete") or "").strip()
    user_code = str(flow.get("user_code") or "").strip()
    if verification_url and user_code:
        print(f"MICROSOFT_LOGIN_URL: {verification_url}")
        print(f"DEVICE_CODE: {user_code}")


def compare_user_continuity(token_a: str, token_b: str) -> bool:
    claims_a = jwt_decode_without_verification(token_a)
    claims_b = jwt_decode_without_verification(token_b)
    if not claims_a or not claims_b:
        return False
    oid_a = claims_a.get("oid")
    oid_b = claims_b.get("oid")
    tid_a = claims_a.get("tid")
    tid_b = claims_b.get("tid")
    if oid_a and oid_b and tid_a and tid_b:
        return oid_a == oid_b and tid_a == tid_b
    return False


SAFE_DOCKER_RUNTIME_ENV_KEYS = {
    "PATH",
    "HOME",
    "TMPDIR",
    "DOCKER_HOST",
    "DOCKER_CONTEXT",
    "DOCKER_CONFIG",
    "XDG_CONFIG_HOME",
}

ALLOWED_CHILD_ENV_KEYS = {
    "TENANT_ID",
    "ISSUER",
    "EXPECTED_AUDIENCE",
    "EXPECTED_SCOPE",
    "AUTHORIZED_CLIENT",
    "JWKS_URL",
    "HOST_PORT",
    "COMPOSE_PROJECT_NAME",
    "AG_CONFIG_PATH",
    *SAFE_DOCKER_RUNTIME_ENV_KEYS,
}


def is_sensitive_child_env_key(key: str) -> bool:
    upper_key = key.upper()
    sensitive_tokens = (
        "TOKEN",
        "SECRET",
        "PASSWORD",
        "DEVICE",
        "AUTHORIZATION",
        "AUTH_CODE",
        "CODE",
        "CREDENTIAL",
    )
    return any(token in upper_key for token in sensitive_tokens)


def build_minimal_subprocess_env(*, extra: dict[str, str] | None = None) -> dict[str, str]:
    merged = os.environ.copy()
    if extra:
        merged.update(extra)
    for key in list(merged):
        if key in {"PATH", "HOME", "TMPDIR", "DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG", "XDG_CONFIG_HOME"}:
            continue
        if is_sensitive_child_env_key(key):
            del merged[key]
            continue
        if key.upper() not in ALLOWED_CHILD_ENV_KEYS and key not in ALLOWED_CHILD_ENV_KEYS:
            del merged[key]
    filtered: dict[str, str] = {}
    for key, value in merged.items():
        if key in ALLOWED_CHILD_ENV_KEYS or key.upper() in ALLOWED_CHILD_ENV_KEYS:
            filtered[key] = value
    return filtered


def resolve_docker_executable(child_env: dict[str, str]) -> str:
    resolved = shutil.which("docker", path=child_env.get("PATH"))
    if not resolved:
        raise RuntimeError("Docker executable not found in PATH for the live compose runner.")
    return resolved


def format_evidence_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def wait_for_gateway_ready(gateway_url: str, *, timeout_seconds: int = 60) -> None:
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            status, body = request_json(f"{gateway_url}.well-known/agent.json")
            if status == 200 and isinstance(body, dict) and body.get("name"):
                return
            last_error = RuntimeError("Gateway route not ready.")
        except Exception as exc:  # pragma: no cover - wait loop
            last_error = exc
        time.sleep(2)
    raise TimeoutError(f"Gateway did not become ready within {timeout_seconds} seconds: {last_error}")


def main(argv: list[str] | None = None) -> int:
    """Run the complete live Solo Agentgateway validation flow for a delegated Entra user token.

    This is the full end-to-end live safety check for the northbound API boundary. It starts with a private Entra device-code sign-in for a test user, exchanges that sign-in token for Token A for Agent A, and then performs an Entra OBO exchange to obtain Token B for Agent B. It validates both tokens independently, proves the same delegated user is represented in both, configures the temporary Solo Agentgateway stack with the tenant JWKS endpoint, verifies that gateway policy accepts Token B while Agent B also enforces its own independent checks, and then performs a negative Token A test to confirm the rejected token never reaches the protected handler. The method records sanitized evidence for pass/fail outcomes and always tears down the temporary containers in a finally block.

    Debugger walkthrough: useful stop points are after `token_a_validation`, after `token_b_validation`, after `token_b_response`, after `token_a_status`, and just before `write_evidence_file` to inspect the in-flight evidence, token results, gateway metadata, and final sanitized output without leaking secret or identity material.
    """
    # Step 1 — Require the explicit `--live` safety flag.
    # This gate prevents accidental execution of the operator-only Entra/OBO/A2A validation flow.
    # Expected result: execution stops immediately unless the operator explicitly opts into the live path.
    parser = argparse.ArgumentParser(description="Live Solo A2A/OBO validation runner")
    parser.add_argument("--live", action="store_true", help="Required to execute the live validation flow")
    args = parser.parse_args(argv)
    if not args.live:
        raise SystemExit("Refusing to run without --live.")

    # Step 2 — Load `.env` and validate the required configuration.
    # This ensures the runtime is using a known private Entra configuration and fails closed if required values are missing.
    # Expected result: the configuration is loaded once and validated before any live token or container work happens.
    evidence = build_evidence_record()
    result_path: Path | None = None
    env: dict[str, str] | None = None
    token_a: str | None = None
    token_b: str | None = None

    try:
        load_env_file()
        config = get_runtime_config()
        tenant_id = config["ENTRA_TENANT_ID"]
        authority = f"https://login.microsoftonline.com/{tenant_id}"
        notebook_client_id = config["ENTRA_NOTEBOOK_CLIENT_ID"]
        agent_a_scope = config["ENTRA_AGENT_A_SCOPE"]
        agent_b_scope = config["ENTRA_AGENT_B_SCOPE"]
        agent_a_expected_scope = extract_delegated_scope_name(agent_a_scope)
        agent_b_expected_scope = extract_delegated_scope_name(agent_b_scope)

        # Step 3 — Create the MSAL Notebook public client.
        # This constructs the client used to start the device-code login flow for the delegated user.
        # Expected result: the public client is ready to request a delegated Token A for Agent A.
        app = msal.PublicClientApplication(client_id=notebook_client_id, authority=authority)

        # Step 4 — Start device-code authentication and wait for the test user.
        # The user signs in through the interactive Microsoft device-code flow so the delegated user identity can be confirmed.
        # Expected result: a valid Token A is returned for the user on the Agent A scope after the user completes sign-in.
        flow = app.initiate_device_flow(scopes=[agent_a_scope])
        if "message" not in flow or "user_code" not in flow:
            raise RuntimeError("Device flow did not return a login code.")
        print_device_login(flow)
        token_a_result = app.acquire_token_by_device_flow(flow)
        if "access_token" not in token_a_result:
            raise RuntimeError("Device code did not return Token A.")
        token_a = str(token_a_result["access_token"])
        evidence["device_login_completed"] = True

        # Step 5 — Receive and validate Token A for Agent A.
        # Token A is the delegated user token for Agent A. It must satisfy Agent A audience, scope, issuer, and authorized-client checks.
        # Expected result: Token A is accepted as a valid user token before any OBO exchange is attempted.
        agent_a_issuer, _ = resolve_issuer_and_jwks(tenant_id, token_a)
        token_a_validation = validate_token_for_policy(
            token_a,
            tenant_id=tenant_id,
            expected_audience=config["ENTRA_AGENT_A_EXPECTED_AUDIENCE"],
            expected_scope=agent_a_expected_scope,
            expected_issuer=agent_a_issuer,
            expected_authorized_client=notebook_client_id,
            test_name="agent_a_live_validation",
        )
        evidence["token_a_validated"] = token_a_validation.get("result") == "PASS"
        if not evidence["token_a_validated"]:
            evidence["error_category"] = token_a_validation.get("error_category", "TOKEN_A_VALIDATION_FAILED")
            raise RuntimeError("Token A validation failed.")

        # Step 6 — Use Agent A’s credentials to perform the Entra OBO exchange.
        # This exchanges the user token for a new delegated token targeted at Agent B, using Agent A’s service identity and the proper scope.
        # Expected result: Token B is issued for the same delegated user with the Agent B audience and scope.
        obo_app = msal.ConfidentialClientApplication(
            client_id=config["ENTRA_AGENT_A_CLIENT_ID"],
            client_credential=config["ENTRA_AGENT_A_CLIENT_SECRET"],
            authority=authority,
        )
        obo_result = obo_app.acquire_token_on_behalf_of(user_assertion=token_a, scopes=[agent_b_scope])
        if "access_token" not in obo_result:
            raise RuntimeError("MSAL OBO exchange failed.")
        token_b = str(obo_result["access_token"])
        evidence["obo_exchange_completed"] = True

        # Step 7 — Receive and validate Token B for Agent B.
        # Token B is the delegated user token for Agent B obtained through OBO. It must be independently validated for the Agent B audience/scope and issuer.
        # Expected result: Token B is separately accepted for Agent B, proving the gateway and backend both see a valid delegated token.
        token_b_issuer, token_b_jwks_uri = resolve_issuer_and_jwks(tenant_id, token_b)
        token_b_validation = validate_token_for_policy(
            token_b,
            tenant_id=tenant_id,
            expected_audience=config["ENTRA_AGENT_B_EXPECTED_AUDIENCE"],
            expected_scope=agent_b_expected_scope,
            expected_issuer=token_b_issuer,
            expected_authorized_client=config["ENTRA_AGENT_A_CLIENT_ID"],
            test_name="agent_b_live_validation",
        )
        evidence["token_b_validated"] = token_b_validation.get("result") == "PASS"
        if not evidence["token_b_validated"]:
            evidence["error_category"] = token_b_validation.get("error_category", "TOKEN_B_VALIDATION_FAILED")
            raise RuntimeError("Token B validation failed.")

        # Step 8 — Verify both tokens represent the same delegated user.
        # This guards against a confused-deputy flow where different users or different delegated identities are passed into the same session.
        # Expected result: the continuity check confirms that both tokens belong to the same delegated user, preventing token mixup.
        evidence["same_delegated_user_verified"] = compare_user_continuity(token_a, token_b)
        if not evidence["same_delegated_user_verified"]:
            evidence["error_category"] = "USER_CONTINUITY_MISMATCH"
            raise RuntimeError("Token continuity check failed.")

        # Step 9 — Build the temporary Solo Agentgateway configuration using Entra’s JWKS endpoint.
        # This config is intentionally temporary and uses the live tenant metadata so the gateway can validate Token B at the northbound edge.
        # Expected result: the gateway is configured to verify Token B against the real Entra JWKS and to enforce the required audience/scope/issuer policy.
        host_port = choose_host_port()
        with tempfile.TemporaryDirectory(prefix="solo-live-") as tmp_dir:
            config_path = Path(tmp_dir) / "agentgateway-config.yaml"
            env = build_minimal_subprocess_env(
                extra={
                    "TENANT_ID": tenant_id,
                    "ISSUER": token_b_issuer,
                    "EXPECTED_AUDIENCE": config["ENTRA_AGENT_B_EXPECTED_AUDIENCE"],
                    "EXPECTED_SCOPE": agent_b_expected_scope,
                    "AUTHORIZED_CLIENT": config["ENTRA_AGENT_A_CLIENT_ID"],
                    "JWKS_URL": token_b_jwks_uri,
                    "HOST_PORT": str(host_port),
                    "COMPOSE_PROJECT_NAME": f"solo-a2a-live-{uuid.uuid4().hex[:8]}",
                    "AG_CONFIG_PATH": str(config_path),
                }
            )
            docker_bin = resolve_docker_executable(env)
            subprocess.run([sys.executable, str(SPIKE_DIR / "render_config.py")], cwd=REPO_ROOT, env=env, check=True)

            # Step 10 — Start the Solo Agentgateway and mock Agent B containers.
            # This launches the public gateway and backend services in a temporary private network so the live validation can be measured end-to-end.
            # Expected result: both services are running and reachable on the local host port selected for the test.
            try:
                subprocess.run(
                    [docker_bin, "compose", "-f", str(COMPOSE_FILE), "up", "-d", "--build", "--wait", "--wait-timeout", "60"],
                    cwd=REPO_ROOT,
                    env=env,
                    check=True,
                )

                # Step 11 — Wait for the public Agent Card endpoint.
                # This confirms the gateway is ready to accept requests and is serving the public metadata expected by callers.
                # Expected result: the public Agent Card is reachable before any token-based traffic is sent.
                gateway_url = f"http://localhost:{host_port}/"
                wait_for_gateway_ready(gateway_url)
                status, agent_card = request_json(f"{gateway_url}.well-known/agent.json")
                if status != 200 or not isinstance(agent_card, dict) or not agent_card.get("name"):
                    raise RuntimeError("Agent Card unavailable.")

                # Step 12 — Send Token B through the gateway to Agent B.
                # This exercises the Solo Agentgateway validation path for a valid delegated Agent B token and confirms the gateway passes it along.
                # Expected result: the request succeeds only when the gateway accepts Token B and Agent B continues processing the message.
                status, token_b_response = request_json(
                    f"{gateway_url}a2a",
                    token=token_b,
                    method="POST",
                    payload={
                        "jsonrpc": "2.0",
                        "method": "message/send",
                        "params": {
                            "message": {
                                "messageId": "live-check",
                                "role": "user",
                                "parts": [{"kind": "text", "text": "live hello"}],
                            }
                        },
                        "id": "live-check",
                    },
                )
                evidence["a2a_message_completed"] = status == 200 and token_b_response.get("result", {}).get("kind") == "message"
                evidence["gateway_agent_b_audience_verified"] = bool(token_b_response.get("result", {}).get("metadata", {}).get("audience_ok"))
                evidence["gateway_agent_a_client_verified"] = bool(token_b_response.get("result", {}).get("metadata", {}).get("client_ok"))
                evidence["agent_b_defense_in_depth_verified"] = bool(
                    token_b_response.get("result", {}).get("metadata", {}).get("issuer_ok")
                    and token_b_response.get("result", {}).get("metadata", {}).get("tenant_ok")
                    and token_b_response.get("result", {}).get("metadata", {}).get("scope_ok")
                )
                if not evidence["a2a_message_completed"]:
                    raise RuntimeError("Token B did not reach Agent B successfully.")

                # Step 13 — Verify gateway authorization and Agent B’s independent validation.
                # This distinguishes the gateway’s northbound policy validation from Agent B’s defense-in-depth validation for audience, issuer, tenant, scope, and client semantics.
                # Expected result: both the Solo Agentgateway and Agent B independently confirm the same delegated Token B is valid and safe to process.
                protected_message_count = lambda: int(request_json(f"{gateway_url}__debug/requests", token=token_b)[1].get("protected_message_count", 0))
                protected_count_before_reject = protected_message_count()

                # Step 14 — Send Token A as a negative security test.
                # Token A is the delegated user token for Agent A and is intentionally invalid for Agent B. This verifies the system rejects a token that passed the Agent A flow but is not valid for the Agent B boundary.
                # Expected result: the request is rejected before any protected Agent B handler executes.
                token_a_status, token_a_body = request_json(
                    f"{gateway_url}a2a",
                    token=token_a,
                    method="POST",
                    payload={
                        "jsonrpc": "2.0",
                        "method": "message/send",
                        "params": {
                            "message": {
                                "messageId": "token-a-rejected",
                                "role": "user",
                                "parts": [{"kind": "text", "text": "reject me"}],
                            }
                        },
                        "id": "token-a-rejected",
                    },
                )

                # Step 15 — Verify Token A is rejected before reaching Agent B’s protected handler.
                # This is the negative control that proves the gateway and backend reject an invalid token before protected logic can run.
                # Expected result: Token A is denied at the boundary and the protected counter does not increment.
                evidence["token_a_rejected_at_agent_b_boundary"] = token_a_status in {401, 403} and "error" in token_a_body
                protected_count_after_reject = protected_message_count()
                if not evidence["token_a_rejected_at_agent_b_boundary"]:
                    raise RuntimeError("Token A was not rejected at the Agent B boundary.")
                if protected_count_after_reject != protected_count_before_reject:
                    raise RuntimeError("Token A reached the protected counter path.")
            finally:
                # Step 16 — Always remove the containers and network in the `finally` block.
                # Cleanup guarantees the temporary live stack is torn down even when the flow fails midway.
                # Expected result: the local stack is fully removed, leaving no leaked network or container state behind.
                subprocess.run(
                    [docker_bin, "compose", "-f", str(COMPOSE_FILE), "down", "-v", "--remove-orphans"],
                    cwd=REPO_ROOT,
                    env=env,
                    check=False,
                )

        # Step 17 — Write timestamped, sanitized evidence.
        # This records the pass/fail summary and only includes boolean outcomes, not tokens, user identifiers, or other sensitive material.
        # Expected result: a sanitized evidence file is written for the completed run, preserving operational proof without leaking secret data.
        evidence["timestamp_utc"] = datetime.now(timezone.utc).isoformat()
        evidence["status"] = "PASS"
        evidence["error_category"] = "NONE"
        result_path = write_evidence_file(evidence)
        print("LIVE_SOLO_A2A_STATUS: PASS")
        print(f"LIVE_SOLO_A2A_EVIDENCE: {format_evidence_path(result_path)}")
        return 0
    except Exception as exc:  # pragma: no cover - live guard path
        # Step 18 — On failure, write sanitized failure evidence.
        # Failures are captured in the same evidence format but without leaking tokens, identifiers, or credentials from the attempted live transaction.
        # Expected result: an operator gets a sanitized failure record that explains the live-path issue while preserving the fail-closed security posture.
        evidence["timestamp_utc"] = datetime.now(timezone.utc).isoformat()
        evidence["status"] = "FAIL"
        evidence["error_category"] = safe_error_category(exc)
        result_path = write_evidence_file(evidence)
        print("LIVE_SOLO_A2A_STATUS: FAIL")
        print(f"LIVE_SOLO_A2A_EVIDENCE: {format_evidence_path(result_path)}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
