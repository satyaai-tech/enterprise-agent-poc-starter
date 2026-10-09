from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


def current_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_state_dir() -> Path:
    state_dir = Path(os.environ.get("SPIKE_STATE_DIR", "/tmp/spike-state"))
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir


def load_state_file(state_dir: Path) -> Path:
    return state_dir / "agent-a-state.json"


class AgentAMockHandler(BaseHTTPRequestHandler):
    server_version = "Phase0AgentAMock/1.0"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return

    def _send_json(self, status: HTTPStatus | int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _state_file(self) -> Path:
        return load_state_file(load_state_dir())

    def _update_state(self, correlation_id: str | None) -> dict[str, Any]:
        state_file = self._state_file()
        if state_file.exists():
            state = json.loads(state_file.read_text(encoding="utf-8"))
        else:
            state = {"received_count": 0, "last_correlation_id": None, "last_seen_utc": None}
        state["received_count"] += 1
        state["last_correlation_id"] = correlation_id
        state["last_seen_utc"] = current_utc()
        state_file.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return state

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send_json(HTTPStatus.OK, {"status": "ok", "service": "mock-agent-a"})
            return
        if self.path == "/state":
            state_file = self._state_file()
            if state_file.exists():
                self._send_json(HTTPStatus.OK, json.loads(state_file.read_text(encoding="utf-8")))
            else:
                self._send_json(HTTPStatus.OK, {"received_count": 0, "last_correlation_id": None})
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"status": "not-found"})

    def do_POST(self) -> None:
        if self.path not in {"/agent-a", "/agent-a/"}:
            self._send_json(HTTPStatus.NOT_FOUND, {"status": "not-found"})
            return
        correlation_id = self.headers.get("X-Correlation-Id")
        state = self._update_state(correlation_id)
        self._send_json(
            HTTPStatus.OK,
            {
                "status": "PASS",
                "service": "mock-agent-a",
                "received_count": state["received_count"],
                "correlation_id": correlation_id,
            },
        )


def main() -> int:
    server = ThreadingHTTPServer(("0.0.0.0", 9001), AgentAMockHandler)
    print("mock agent a ready")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())