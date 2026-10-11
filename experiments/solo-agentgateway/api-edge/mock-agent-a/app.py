from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self._handle_request()

    def do_POST(self):
        self._handle_request()

    def do_PUT(self):
        self._handle_request()

    def do_DELETE(self):
        self._handle_request()

    def _handle_request(self):
        if self.path == "/__debug/requests":
            body = {
                "status": "ok",
                "service": "mock-agent-a",
                "request_count": getattr(self.server, "request_count", 0),
            }
            payload = json.dumps(body).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        setattr(self.server, "request_count", getattr(self.server, "request_count", 0) + 1)
        body = {
            "status": "ok",
            "service": "mock-agent-a",
            "path": self.path,
            "method": self.command,
            "correlation_id": self.headers.get("X-Correlation-Id", "missing"),
            "authorization_present": bool(self.headers.get("Authorization")),
        }
        payload = json.dumps(body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args):
        return


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", 8080), Handler)
    server.request_count = 0
    server.serve_forever()
