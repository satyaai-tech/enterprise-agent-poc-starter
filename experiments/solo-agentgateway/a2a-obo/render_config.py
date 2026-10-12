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
    audience = required("EXPECTED_AUDIENCE", default="api://agent-b-example")
    expected_scope = required("EXPECTED_SCOPE", default="AgentB.Access")
    authorized_client = required("AUTHORIZED_CLIENT", default="synthetic-agent-a")
    config_path = Path(required("AG_CONFIG_PATH", default="/tmp/agentgateway-config.yaml"))
    jwks_url = os.environ.get("JWKS_URL", "http://jwks-fixture:8081/.well-known/jwks.json")

    auth_policy = (
        f"jwt.iat > 0 && jwt.tid == '{tenant_id}' && "
        f"jwt.scp.split(' ').exists(scope, scope == '{expected_scope}') && "
        f"((jwt.ver == '2.0' && jwt.azp == '{authorized_client}') || "
        f"(jwt.ver == '1.0' && jwt.appid == '{authorized_client}'))"
    )
    jwt_policy = f'''      jwtAuth:
        mode: strict
        issuer: "{issuer}"
        audiences:
          - "{audience}"
        jwks:
          url: "{jwks_url}"
        jwtValidationOptions:
          requiredClaims:
            - exp
            - nbf
            - iss
            - aud
            - tid
            - scp
            - iat
            - ver
      authorization:
        rules:
          - allow: "{auth_policy}"
'''
    config = f'''gateways:
  default:
    port: 8080
    bindAddress: 0.0.0.0
routes:
  - name: public-agent-card
    matches:
      - path:
          pathPrefix: /.well-known/agent.json
    backends:
      - host: "mock-agent-b:8080"
  - name: protected-a2a
    matches:
      - path:
          pathPrefix: /a2a
    policies:
{jwt_policy}    backends:
      - host: "mock-agent-b:8080"
        policies:
          backendAuth:
            passthrough: {{}}
  - name: debug-route
    matches:
      - path:
          pathPrefix: /__debug
    policies:
{jwt_policy}    backends:
      - host: "mock-agent-b:8080"
        policies:
          backendAuth:
            passthrough: {{}}
'''
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(config, encoding="utf-8")
    return str(config_path)


if __name__ == "__main__":
    print(render())
