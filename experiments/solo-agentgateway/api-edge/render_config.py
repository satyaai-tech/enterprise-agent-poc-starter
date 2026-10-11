#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path


def required(var: str, *, default: str | None = None) -> str:
    value = os.environ.get(var, default)
    if value is None:
        raise RuntimeError(f"Missing required environment variable: {var}")
    return value


def render() -> str:
    tenant_id = required("TENANT_ID")
    issuer = required("ISSUER", default=f"https://login.microsoftonline.com/{tenant_id}/v2.0")
    audience = required("EXPECTED_AUDIENCE", default="api://agent-a-example")
    expected_scope = required("EXPECTED_SCOPE", default="AgentA.Access")
    authorized_client = required("AUTHORIZED_CLIENT", default="synthetic-client")
    config_path = Path(required("AG_CONFIG_PATH", default="/tmp/agentgateway-config.yaml"))

    config = f'''gateways:
  default:
    port: 8080
    bindAddress: 0.0.0.0
    jwtAuth:
      mode: strict
      issuer: "{issuer}"
      audiences:
        - "{audience}"
      jwks:
        url: "http://jwks-fixture:8081/.well-known/jwks.json"
      jwtValidationOptions:
        requiredClaims:
          - exp
          - nbf
          - iss
          - aud
    authorization:
      rules:
        - allow: "jwt.iat > 0 && jwt.tid == '{tenant_id}' && jwt.azp == '{authorized_client}' && jwt.scp.split(' ').exists(scope, scope == '{expected_scope}')"
routes:
  - name: mock-agent-a
    matches:
      - path:
          pathPrefix: /
    backends:
      - host: "mock-agent-a:8080"
'''
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(config, encoding="utf-8")
    return str(config_path)


if __name__ == "__main__":
    print(render())
