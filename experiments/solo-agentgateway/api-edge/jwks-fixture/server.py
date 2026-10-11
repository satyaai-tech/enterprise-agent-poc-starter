from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def load_jwks() -> dict:
    jwks_file = Path(os.environ.get("JWKS_FILE", "/data/jwks.json"))
    if not jwks_file.exists():
        raise FileNotFoundError(f"JWKS fixture file not found: {jwks_file}")
    return json.loads(jwks_file.read_text(encoding="utf-8"))


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in {"/.well-known/jwks.json", "/jwks.json", "/.well-known/openid-configuration"}:
            if self.path == "/.well-known/openid-configuration":
                body = {
                    "issuer": os.environ.get("ISSUER", "https://issuer.example.test"),
                    "jwks_uri": "http://jwks-fixture:8081/.well-known/jwks.json",
                }
            else:
                body = load_jwks()
            payload = json.dumps(body).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, format: str, *args):
        return


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", 8081), Handler)
    server.serve_forever()
