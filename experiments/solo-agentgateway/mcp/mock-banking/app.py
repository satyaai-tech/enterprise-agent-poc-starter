from __future__ import annotations

import json
import os
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib import request

import jwt

_READ_TOOLS = {"get_account_summary"}
_WRITE_TOOLS = {"create_transfer"}
_ALLOWED_TOOLS = _READ_TOOLS | _WRITE_TOOLS
_ACCOUNT_OWNERS = {
    "acct-1001": "user-12345",
    "acct-2002": "user-12345",
    "acct-3003": "user-12345",
    "acct-9000": "user-67890",
}
_IDEMPOTENCY_KEYS: dict[str, dict[str, Any]] = {}
STATE: dict[str, Any] = {
    "accounts": {"acct-1001": 12345.67, "acct-2002": 250.0},
    "transfers": [],
    "debug": {
        "requests_total": 0,
        "tool_calls_total": 0,
        "rejected_total": 0,
        "transfer_attempts_total": 0,
        "transfer_mutations_total": 0,
        "idempotent_retries_total": 0,
    },
}


def load_expected_claims() -> dict[str, str]:
    return {
        "issuer": os.environ.get("ISSUER", "https://login.microsoftonline.com/11111111-2222-3333-4444-555555666666/v2.0"),
        "audience": os.environ.get("EXPECTED_AUDIENCE", "api://banking-mock"),
        "tenant_id": os.environ.get("TENANT_ID", "11111111-2222-3333-4444-555555666666"),
        "authorized_client": os.environ.get("AUTHORIZED_CLIENT", "synthetic-agent-b"),
    }


def _fetch_jwks_document(url: str) -> dict[str, Any] | None:
    try:
        with request.urlopen(url, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("keys"), list):
        return None
    return payload


def load_jwks_document() -> dict[str, Any] | None:
    jwks_url = os.environ.get("JWKS_URL")
    if jwks_url:
        return _fetch_jwks_document(jwks_url)
    jwks_path = os.environ.get("JWKS_FILE", "/data/jwks.json")
    try:
        with open(jwks_path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except Exception:
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("keys"), list):
        return None
    return payload


def load_public_key(token: str):
    payload = load_jwks_document()
    if payload is None:
        return None
    try:
        header = jwt.get_unverified_header(token)
    except Exception:
        return None
    kid = header.get("kid")
    if not kid:
        return None
    for key in payload.get("keys", []):
        if key.get("kid") == kid:
            try:
                return jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(key))
            except Exception:
                return None
    return None


def validate_token(token: str) -> dict[str, Any] | None:
    claims = load_expected_claims()
    public_key = load_public_key(token)
    if public_key is None:
        return None
    try:
        principal = jwt.decode(
            token,
            key=public_key,
            algorithms=["RS256"],
            audience=claims["audience"],
            issuer=claims["issuer"],
            options={
                "require": ["exp", "nbf", "iss", "aud", "tid", "scp", "iat", "ver"],
                "verify_signature": True,
                "verify_aud": True,
                "verify_exp": True,
                "verify_nbf": True,
                "verify_iat": True,
                "verify_iss": True,
            },
        )
    except Exception:
        return None

    expected_tenant = claims["tenant_id"]
    expected_client = claims["authorized_client"]
    token_scopes = set(str(principal.get("scp") or "").split())

    if principal.get("tid") != expected_tenant:
        return None
    if principal.get("aud") != claims["audience"]:
        return None
    if principal.get("iss") != claims["issuer"]:
        return None
    version = str(principal.get("ver") or principal.get("v") or "2.0")
    client_name = "azp" if version == "2.0" else "appid"
    if principal.get(client_name) != expected_client:
        return None
    if "Banking.Read" not in token_scopes and "Banking.Write" not in token_scopes:
        return None
    return {
        "tenant_ok": True,
        "audience_ok": True,
        "issuer_ok": True,
        "client_ok": True,
        "scopes": token_scopes,
        "sub": str(principal.get("sub") or principal.get("oid") or ""),
        "oid": str(principal.get("oid") or principal.get("sub") or ""),
    }



def reset_backend_state() -> None:
    global STATE, _IDEMPOTENCY_KEYS
    STATE = {
        "accounts": {"acct-1001": 12345.67, "acct-2002": 250.0},
        "transfers": [],
        "debug": {
            "requests_total": 0,
            "tool_calls_total": 0,
            "rejected_total": 0,
            "transfer_attempts_total": 0,
            "transfer_mutations_total": 0,
            "idempotent_retries_total": 0,
        },
    }
    _IDEMPOTENCY_KEYS = {}


def _debug_snapshot() -> dict[str, Any]:
    return {
        "requests_total": int(STATE["debug"]["requests_total"]),
        "tool_calls_total": int(STATE["debug"]["tool_calls_total"]),
        "rejected_total": int(STATE["debug"]["rejected_total"]),
        "transfer_attempts_total": int(STATE["debug"]["transfer_attempts_total"]),
        "transfer_mutations_total": int(STATE["debug"]["transfer_mutations_total"]),
        "idempotent_retries_total": int(STATE["debug"]["idempotent_retries_total"]),
        "transfer_count": len(STATE["transfers"]),
    }


def _effective_account_owner(account_id: str) -> str:
    configured_owner = (os.environ.get("BANKING_TEST_USER_OID") or "").strip()
    if configured_owner:
        return configured_owner
    owner = _ACCOUNT_OWNERS.get(account_id)
    if owner:
        return owner
    return "user-12345"


def _account_owner_for(subject: str, account_id: str) -> bool:
    return _effective_account_owner(account_id) == subject


def jsonrpc_error(code: int, message: str, *, request_id: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"jsonrpc": "2.0", "error": {"code": code, "message": message}}
    if request_id is not None:
        payload["id"] = request_id
    return payload


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/healthz":
            self._respond_json(200, {"status": "ok", "service": "mock-banking"})
            return
        if self.path in {"/__debug/metrics", "/__debug/state"}:
            self._respond_json(200, _debug_snapshot())
            return
        if self.path == "/__debug/reset":
            reset_backend_state()
            self._respond_json(200, {"status": "reset", "service": "mock-banking"})
            return
        self._respond_json(404, {"status": "not_found"})

    def do_POST(self):
        if self.path == "/__debug/reset":
            reset_backend_state()
            self._respond_json(200, {"status": "reset", "service": "mock-banking"})
            return
        if self.path != "/mcp":
            self._respond_json(404, {"status": "not_found"})
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length) if content_length else b"{}"
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            self._respond_json(400, jsonrpc_error(-32600, "Request body must be valid JSON"))
            return

        STATE["debug"]["requests_total"] += 1

        auth_header = self.headers.get("Authorization")
        if not auth_header or not auth_header.lower().startswith("bearer "):
            STATE["debug"]["rejected_total"] += 1
            self._respond_json(401, jsonrpc_error(-32001, "Bearer token required"))
            return

        token = auth_header.split(" ", 1)[1].strip()
        principal = validate_token(token)
        if principal is None:
            STATE["debug"]["rejected_total"] += 1
            self._respond_json(403, jsonrpc_error(-32002, "JWT validation failed"))
            return

        method = payload.get("method")
        request_id = payload.get("id")

        if method == "initialize":
            session_id = uuid.uuid4().hex
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "mock-banking", "version": "1.0.0"},
                },
            }
            self._respond_json(200, response, extra_headers={"Mcp-Session-Id": session_id})
            return

        if method == "notifications/initialized":
            self.send_response(202)
            self.send_header("Mcp-Session-Id", self.headers.get("Mcp-Session-Id", uuid.uuid4().hex))
            self.end_headers()
            return

        if method == "tools/list":
            allowed_tools: list[dict[str, Any]] = []
            token_scopes = principal["scopes"]
            if "Banking.Read" in token_scopes:
                allowed_tools.append({
                    "name": "get_account_summary",
                    "description": "Read account summary",
                    "inputSchema": {"type": "object", "properties": {"account_id": {"type": "string"}}, "required": ["account_id"]},
                })
            if "Banking.Write" in token_scopes:
                allowed_tools.append({
                    "name": "create_transfer",
                    "description": "Create outbound transfer",
                    "inputSchema": {"type": "object", "properties": {"from_account": {"type": "string"}, "to_account": {"type": "string"}, "amount": {"type": "number"}, "confirmation": {"type": "string"}}, "required": ["from_account", "to_account", "amount", "confirmation"]},
                })
            self._respond_json(200, {"jsonrpc": "2.0", "result": {"tools": allowed_tools}, "id": request_id})
            return

        if method == "tools/call":
            STATE["debug"]["tool_calls_total"] += 1
            params = payload.get("params", {})
            tool_name = params.get("name")
            arguments = params.get("arguments", {})

            if tool_name not in _ALLOWED_TOOLS:
                STATE["debug"]["rejected_total"] += 1
                self._respond_json(403, jsonrpc_error(-32003, f"Tool not allowed: {tool_name}", request_id=request_id))
                return

            token_scopes = principal["scopes"]
            if tool_name in _READ_TOOLS and "Banking.Read" not in token_scopes:
                STATE["debug"]["rejected_total"] += 1
                self._respond_json(403, jsonrpc_error(-32004, "Missing Banking.Read scope", request_id=request_id))
                return
            if tool_name in _WRITE_TOOLS and "Banking.Write" not in token_scopes:
                STATE["debug"]["rejected_total"] += 1
                self._respond_json(403, jsonrpc_error(-32005, "Missing Banking.Write scope", request_id=request_id))
                return

            subject = str(principal.get("oid") or principal.get("sub") or "")

            if tool_name == "get_account_summary":
                account_id = str(arguments.get("account_id", "acct-1001"))
                if not _account_owner_for(subject, account_id):
                    STATE["debug"]["rejected_total"] += 1
                    self._respond_json(403, jsonrpc_error(-32007, "Account not authorized for this user", request_id=request_id))
                    return
                balance = STATE["accounts"].get(account_id, 0.0)
                self._respond_json(200, {
                    "jsonrpc": "2.0",
                    "result": {
                        "content": [{"type": "text", "text": f"Balance for {account_id} is {balance:.2f}"}],
                        "structuredContent": {"account_id": account_id, "balance": float(balance)},
                    },
                    "id": request_id,
                })
                return

            if tool_name == "create_transfer":
                STATE["debug"]["transfer_attempts_total"] += 1
                idempotency_key = (self.headers.get("X-Idempotency-Key") or "").strip()
                if not idempotency_key:
                    STATE["debug"]["rejected_total"] += 1
                    self._respond_json(400, jsonrpc_error(-32008, "Missing X-Idempotency-Key header", request_id=request_id))
                    return
                from_account = str(arguments.get("from_account", "acct-1001"))
                to_account = str(arguments.get("to_account", "acct-2002"))
                amount = float(arguments.get("amount", 0.0))
                confirmation = str(arguments.get("confirmation", "")).lower()
                if not _account_owner_for(subject, from_account):
                    STATE["debug"]["rejected_total"] += 1
                    self._respond_json(403, jsonrpc_error(-32009, "Source account not authorized for this user", request_id=request_id))
                    return
                if not _account_owner_for(subject, to_account):
                    STATE["debug"]["rejected_total"] += 1
                    self._respond_json(403, jsonrpc_error(-32010, "Destination account is not owned by this user", request_id=request_id))
                    return
                if confirmation != "yes":
                    STATE["debug"]["rejected_total"] += 1
                    self._respond_json(403, jsonrpc_error(-32006, "Transfer requires explicit confirmation", request_id=request_id))
                    return
                if amount <= 0:
                    STATE["debug"]["rejected_total"] += 1
                    self._respond_json(400, jsonrpc_error(-32011, "Transfer amount must be greater than zero", request_id=request_id))
                    return
                fingerprint = json.dumps({
                    "from_account": from_account,
                    "to_account": to_account,
                    "amount": float(amount),
                    "confirmation": confirmation,
                }, sort_keys=True)
                storage_key = f"{subject}:{idempotency_key}"
                existing = _IDEMPOTENCY_KEYS.get(storage_key)
                if existing is not None:
                    if existing["fingerprint"] == fingerprint:
                        STATE["debug"]["idempotent_retries_total"] += 1
                        self._respond_json(200, existing["response"])
                        return
                    STATE["debug"]["rejected_total"] += 1
                    self._respond_json(409, jsonrpc_error(-32012, "Idempotency key already used for a different transfer", request_id=request_id))
                    return
                transfer_id = f"txn-{len(STATE['transfers']) + 1:04d}"
                response = {
                    "jsonrpc": "2.0",
                    "result": {
                        "transfer_id": transfer_id,
                        "content": [{"type": "text", "text": f"Transfer created for {to_account} amount {amount:.2f}"}],
                        "structuredContent": {"transfer_id": transfer_id, "to_account": to_account, "amount": float(amount), "status": "created"},
                    },
                    "id": request_id,
                }
                STATE["transfers"].append({"transfer_id": transfer_id, "from_account": from_account, "to_account": to_account, "amount": amount, "confirmed": True, "owner": subject})
                STATE["debug"]["transfer_mutations_total"] += 1
                _IDEMPOTENCY_KEYS[storage_key] = {"fingerprint": fingerprint, "response": response}
                self._respond_json(200, response)
                return

            self._respond_json(403, jsonrpc_error(-32003, f"Tool not allowed: {tool_name}", request_id=request_id))
            return

        self._respond_json(400, jsonrpc_error(-32601, "Unsupported method", request_id=request_id))

    def _respond_json(self, status: int, payload: dict[str, Any], *, extra_headers: dict[str, str] | None = None) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        if extra_headers:
            for key, value in extra_headers.items():
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
