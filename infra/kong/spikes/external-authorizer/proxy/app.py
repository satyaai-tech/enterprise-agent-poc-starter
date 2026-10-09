from __future__ import annotations

import http.client
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from phase0_validation import build_evidence_destination, sha256_fingerprint, validate_token_for_policy, write_evidence


@dataclass(frozen=True)
class ProxySettings:
    tenant_id: str
    expected_audience: str
    expected_scope: str
    expected_authorized_client: str
    expected_issuer: str
    openid_configuration_path: Path
    jwks_path: Path
    evidence_dir: Path
    upstream_url: str
    correlation_header: str = "X-Correlation-Id"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_settings() -> ProxySettings:
    openid_configuration_path = Path(os.environ["SPIKE_OPENID_CONFIGURATION_PATH"])
    openid_configuration = load_json(openid_configuration_path)
    return ProxySettings(
        tenant_id=os.environ["SPIKE_TENANT_ID"],
        expected_audience=os.environ["SPIKE_EXPECTED_AUDIENCE"],
        expected_scope=os.environ["SPIKE_EXPECTED_SCOPE"],
        expected_authorized_client=os.environ["SPIKE_EXPECTED_AUTHORIZED_CLIENT"],
        expected_issuer=openid_configuration["issuer"],
        openid_configuration_path=openid_configuration_path,
        jwks_path=Path(os.environ["SPIKE_JWKS_PATH"]),
        evidence_dir=Path(os.environ["SPIKE_EVIDENCE_DIR"]),
        upstream_url=os.environ["SPIKE_UPSTREAM_URL"],
        correlation_header=os.environ.get("SPIKE_CORRELATION_HEADER", "X-Correlation-Id"),
    )


def current_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def bearer_token_from_header(header_value: str | None) -> tuple[str | None, str | None]:
    if not header_value:
        return None, "MISSING_TOKEN"
    parts = header_value.strip().split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        return None, "MALFORMED_TOKEN"
    return parts[1].strip(), None


class SpikeHandler(BaseHTTPRequestHandler):
    server_version = "Phase0ValidationProxy/1.0"

    @property
    def settings(self) -> ProxySettings:
        return self.server.settings  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return

    def _send_json(self, status: HTTPStatus | int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _request_correlation_id(self) -> str:
        incoming = self.headers.get(self.settings.correlation_header)
        if incoming and incoming.strip():
            return incoming.strip()
        return uuid4().hex

    def _openid_configuration_provider(self, tenant_id: str, version: str, timeout: int) -> dict[str, Any]:
        return load_json(self.settings.openid_configuration_path)

    def _jwks_provider(self, jwks_uri: str, timeout: int) -> dict[str, Any]:
        return load_json(self.settings.jwks_path)

    def _forward_to_agent_a(self, correlation_id: str, validation: dict[str, Any]) -> dict[str, Any]:
        parsed = urlparse(self.settings.upstream_url)
        connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
        payload = {
            "correlation_id": correlation_id,
            "validated": True,
            "scope": validation.get("scope_verified", False),
        }
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            self.settings.correlation_header: correlation_id,
        }
        connection.request("POST", parsed.path or "/agent-a", body=body, headers=headers)
        response = connection.getresponse()
        response_body = response.read().decode("utf-8")
        connection.close()
        return {
            "status": response.status,
            "body": json.loads(response_body) if response_body else {},
        }

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send_json(HTTPStatus.OK, {"status": "ok", "service": "validation-proxy"})
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"status": "not-found"})

    def do_POST(self) -> None:
        if self.path not in {"/", "/agent-a", "/agent-a/"}:
            self._send_json(HTTPStatus.NOT_FOUND, {"status": "not-found"})
            return

        correlation_id = self._request_correlation_id()
        authorization = self.headers.get("Authorization")
        token, token_error = bearer_token_from_header(authorization)
        if token_error is not None:
            evidence = {
                "timestamp_utc": current_utc(),
                "correlation_id": correlation_id,
                "status": "FAIL",
                "source": "kong-external-authorizer-spike",
                "result": {
                    "result": "FAIL",
                    "error_category": token_error,
                    "test_name": "proxy_request_validation",
                    "token_fingerprint": None,
                },
                "upstream": {"reached": False},
            }
            destination = build_evidence_destination(self.settings.evidence_dir)
            write_evidence(evidence, destination=destination)
            self._send_json(HTTPStatus.UNAUTHORIZED, {"status": "FAIL", "error_category": token_error, "correlation_id": correlation_id})
            return

        validation = validate_token_for_policy(
            token,
            tenant_id=self.settings.tenant_id,
            expected_audience=self.settings.expected_audience,
            expected_scope=self.settings.expected_scope,
            expected_issuer=self.settings.expected_issuer,
            expected_authorized_client=self.settings.expected_authorized_client,
            test_name="proxy_request_validation",
            openid_configuration_provider=self._openid_configuration_provider,
            jwks_provider=self._jwks_provider,
        )

        if validation.get("result") != "PASS":
            evidence = {
                "timestamp_utc": current_utc(),
                "correlation_id": correlation_id,
                "status": "FAIL",
                "source": "kong-external-authorizer-spike",
                "validation": validation,
                "upstream": {"reached": False},
            }
            destination = build_evidence_destination(self.settings.evidence_dir)
            write_evidence(evidence, destination=destination)
            status = HTTPStatus.UNAUTHORIZED if validation.get("error_category") in {"MISSING_TOKEN", "MALFORMED_TOKEN", "INVALID_SIGNATURE", "MALFORMED_TOKEN"} else HTTPStatus.FORBIDDEN
            self._send_json(status, {"status": "FAIL", "error_category": validation.get("error_category"), "correlation_id": correlation_id})
            return

        try:
            upstream = self._forward_to_agent_a(correlation_id, validation)
        except OSError:
            evidence = {
                "timestamp_utc": current_utc(),
                "correlation_id": correlation_id,
                "status": "FAIL",
                "source": "kong-external-authorizer-spike",
                "validation": validation,
                "upstream": {"reached": False, "error_category": "UPSTREAM_UNAVAILABLE"},
            }
            destination = build_evidence_destination(self.settings.evidence_dir)
            write_evidence(evidence, destination=destination)
            self._send_json(HTTPStatus.BAD_GATEWAY, {"status": "FAIL", "error_category": "UPSTREAM_UNAVAILABLE", "correlation_id": correlation_id})
            return

        evidence = {
            "timestamp_utc": current_utc(),
            "correlation_id": correlation_id,
            "status": "PASS",
            "source": "kong-external-authorizer-spike",
            "validation": validation,
            "upstream": {"reached": True, "status": upstream["status"], "body": upstream["body"]},
        }
        destination = build_evidence_destination(self.settings.evidence_dir)
        write_evidence(evidence, destination=destination)
        self._send_json(
            HTTPStatus.OK,
            {
                "status": "PASS",
                "correlation_id": correlation_id,
                "upstream": upstream["body"],
                "validation": {
                    "signature_verified": validation.get("signature_verified"),
                    "issuer_verified": validation.get("issuer_verified"),
                    "tenant_verified": validation.get("tenant_verified"),
                    "audience_verified": validation.get("audience_verified"),
                    "lifetime_verified": validation.get("lifetime_verified"),
                    "scope_verified": validation.get("scope_verified"),
                    "authorized_client_verified": validation.get("authorized_client_verified"),
                },
            },
        )


def main() -> int:
    settings = load_settings()
    if not settings.openid_configuration_path.exists():
        raise RuntimeError(f"Missing OpenID configuration fixture: {settings.openid_configuration_path}")
    if not settings.jwks_path.exists():
        raise RuntimeError(f"Missing JWKS fixture: {settings.jwks_path}")
    settings.evidence_dir.mkdir(parents=True, exist_ok=True)

    server = ThreadingHTTPServer(("0.0.0.0", 9000), SpikeHandler)
    server.settings = settings  # type: ignore[attr-defined]
    print("validation proxy ready")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())