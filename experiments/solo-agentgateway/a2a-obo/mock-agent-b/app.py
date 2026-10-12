from __future__ import annotations

import json
import os
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import jwt
from a2a.types import AgentCard, Message, SendMessageRequest, SendMessageSuccessResponse, TextPart

_JWKS_CACHE: str | None = None


def load_expected_claims() -> dict[str, str]:
    return {
        "issuer": os.environ.get("ISSUER", "https://login.microsoftonline.com/11111111-2222-3333-4444-555555666666/v2.0"),
        "audience": os.environ.get("EXPECTED_AUDIENCE", "api://agent-b-example"),
        "scope": os.environ.get("EXPECTED_SCOPE", "AgentB.Access"),
        "tenant_id": os.environ.get("TENANT_ID", "11111111-2222-3333-4444-555555666666"),
        "authorized_client": os.environ.get("AUTHORIZED_CLIENT", "synthetic-agent-a"),
    }


def build_agent_card() -> dict[str, Any]:
    values = {
        "name": "mock-agent-b",
        "description": "Synthetic Agent B behind the local agentgateway validation edge.",
        "url": "http://mock-agent-b:8080",
        "version": "1.0.0",
        "protocolVersion": "0.2.5",
        "preferredTransport": "JSONRPC",
        "capabilities": {"streaming": False, "pushNotifications": False, "stateTransitionHistory": False},
        "defaultInputModes": ["text"],
        "defaultOutputModes": ["text"],
        "provider": {"organization": "Synthetic", "url": "https://example.invalid"},
        "security": [],
        "skills": [
            {
                "id": "synthetic-delegated-task",
                "name": "Synthetic delegated task",
                "description": "Returns a sanitized success result when the delegated JWT is valid.",
                "examples": ["hello from agent a"],
                "inputModes": ["text"],
                "outputModes": ["text"],
                "tags": ["synthetic", "delegated"],
            }
        ],
    }
    return AgentCard.model_validate(values).model_dump(mode="json", exclude_none=True)


def load_public_key() -> str | None:
    global _JWKS_CACHE
    jwks_path = Path(os.environ.get("JWKS_FILE", "/data/jwks.json"))
    if not jwks_path.exists():
        _JWKS_CACHE = None
        return None
    if _JWKS_CACHE is not None:
        return _JWKS_CACHE
    payload = json.loads(jwks_path.read_text(encoding="utf-8"))
    for key in payload.get("keys", []):
        if key.get("kid") == "synthetic-kid":
            _JWKS_CACHE = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(key))
            return _JWKS_CACHE
    _JWKS_CACHE = None
    return None


def validate_token(token: str) -> dict[str, Any] | None:
    claims = load_expected_claims()
    public_key = load_public_key()
    if public_key is None:
        return None
    try:
        principal = jwt.decode(
            token,
            key=public_key,
            algorithms=["RS256"],
            audience=claims["audience"],
            issuer=claims["issuer"],
            options={"require": ["exp", "nbf", "iss", "aud", "tid", "scp", "iat"]},
        )
    except Exception:  # noqa: BLE001
        return None

    expected_tenant = claims["tenant_id"]
    expected_client = claims["authorized_client"]
    expected_scope = claims["scope"]

    if principal.get("tid") != expected_tenant:
        return None
    if principal.get("aud") != claims["audience"]:
        return None
    if principal.get("iss") != claims["issuer"]:
        return None
    if principal.get("scp") != expected_scope:
        return None

    version = str(principal.get("ver") or principal.get("v") or "2.0")
    client_name = "azp" if version == "2.0" else "appid"
    if principal.get(client_name) != expected_client:
        return None

    if principal.get("exp") is None or principal.get("nbf") is None or principal.get("iat") is None:
        return None

    return {
        "signature_valid": True,
        "issuer_valid": True,
        "tenant_valid": True,
        "audience_valid": True,
        "scope_valid": True,
        "exp_valid": True,
        "nbf_valid": True,
        "iat_valid": True,
        "client_valid": True,
        "is_valid": True,
    }


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self._handle_request()

    def do_POST(self):
        self._handle_request()

    def _respond_json(self, status: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _handle_request(self):
        if self.path == "/healthz":
            self._respond_json(200, {"status": "ok", "service": "mock-agent-b"})
            return

        if self.path == "/__debug/requests":
            count = getattr(self.server, "protected_message_count", 0)
            self._respond_json(200, {
                "status": "ok",
                "service": "mock-agent-b",
                "protected_message_count": count,
            })
            return

        if self.path == "/.well-known/agent.json":
            self._respond_json(200, build_agent_card())
            return

        auth_header = self.headers.get("Authorization")
        if self.path.startswith("/a2a") or self.path.startswith("/messages"):
            body_length = int(self.headers.get("Content-Length", "0"))
            payload_bytes = self.rfile.read(body_length) if body_length else b""
            request_id = None
            token = None
            if auth_header and auth_header.lower().startswith("bearer "):
                token = auth_header.split(" ", 1)[1]
            if not token:
                self._respond_json(401, {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32001, "message": "Unauthorized"}})
                return

            result = validate_token(token)
            if not result:
                self._respond_json(401, {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32001, "message": "Unauthorized"}})
                return

            try:
                request_body = json.loads(payload_bytes.decode("utf-8")) if payload_bytes else {}
                if request_body:
                    request_id = request_body.get("id")
                    SendMessageRequest.model_validate(request_body)
            except Exception:
                self._respond_json(200, {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32600, "message": "Invalid request"}})
                return

            getattr(self.server, "protected_message_count", 0)
            self.server.protected_message_count = int(getattr(self.server, "protected_message_count", 0)) + 1
            response = SendMessageSuccessResponse(
                id=request_id,
                jsonrpc="2.0",
                result=Message(
                    messageId=str(uuid.uuid4()),
                    role="agent",
                    parts=[TextPart(text="hello from mock-agent-b")],
                    metadata={
                        "authenticated": result["is_valid"],
                        "audience_ok": result["audience_valid"],
                        "scope_ok": result["scope_valid"],
                        "tenant_ok": result["tenant_valid"],
                        "issuer_ok": result["issuer_valid"],
                        "client_ok": result["client_valid"],
                    },
                ),
            )
            self._respond_json(200, response.model_dump(mode="json", exclude_none=True))
            return

        self._respond_json(200, {
            "status": "ok",
            "service": "mock-agent-b",
            "path": self.path,
            "method": self.command,
            "authorization_present": bool(auth_header),
        })

    def log_message(self, format: str, *args):
        return


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", 8080), Handler)
    server.protected_message_count = 0
    server.serve_forever()
