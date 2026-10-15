#!/usr/bin/env python3
from __future__ import annotations

import json
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
    audience = required("EXPECTED_AUDIENCE", default="api://banking-mock")
    expected_scope = required("EXPECTED_SCOPE", default="Banking.Read Banking.Write")
    authorized_client = required("AUTHORIZED_CLIENT", default="synthetic-agent-b")
    config_path = Path(required("AG_CONFIG_PATH", default="/tmp/agentgateway-config.yaml"))
    jwks_url = os.environ.get("JWKS_URL", "http://jwks-fixture:8081/.well-known/jwks.json")
    gateway_resource = os.environ.get("GATEWAY_RESOURCE", "http://localhost:18082/mcp")
    read_rule = (
        "jwt.tid == '{tenant_id}' &&\n"
        "((jwt.ver == '2.0' && jwt.azp == '{authorized_client}') ||\n"
        "(jwt.ver == '1.0' && jwt.appid == '{authorized_client}')) &&\n"
        "jwt.scp.split(' ').exists(scope, scope == 'Banking.Read') &&\n"
        "jwt.roles.exists(role, role == 'Banking.Reader' || role == 'Banking.Writer') &&\n"
        "mcp.tool.name == 'get_account_summary'"
    ).format(tenant_id=tenant_id, authorized_client=authorized_client)
    write_rule = (
        "jwt.tid == '{tenant_id}' &&\n"
        "((jwt.ver == '2.0' && jwt.azp == '{authorized_client}') ||\n"
        "(jwt.ver == '1.0' && jwt.appid == '{authorized_client}')) &&\n"
        "jwt.scp.split(' ').exists(scope, scope == 'Banking.Write') &&\n"
        "jwt.roles.exists(role, role == 'Banking.Writer') &&\n"
        "mcp.tool.name == 'create_transfer'"
    ).format(tenant_id=tenant_id, authorized_client=authorized_client)
    config = f'''gateways:
  default:
    port: 8080
    bindAddress: 0.0.0.0
routes:
  - name: health-probe
    matches:
      - path:
          pathPrefix: /healthz
    backends:
      - host: "mock-banking:8080"
  - name: protected-mcp
    matches:
      - path:
          exact: /mcp
    policies:
      cors:
        allowOrigins:
          - "*"
        allowHeaders:
          - "Authorization"
          - "Mcp-Session-Id"
          - "mcp-protocol-version"
          - "content-type"
        exposeHeaders:
          - "Mcp-Session-Id"
      mcpAuthentication:
        mode: strict
        issuer: "{issuer}"
        audiences:
          - "{audience}"
        jwks:
          url: "{jwks_url}"
        resourceMetadata:
          resource: "{gateway_resource}"
          scopesSupported:
            - "Banking.Read"
            - "Banking.Write"
          bearerMethodsSupported:
            - "header"
    backends:
      - mcp:
          targets:
            - name: banking
              mcp:
                host: "http://mock-banking:8080/mcp"
              policies:
                backendAuth:
                  passthrough: {{}}
        policies:
          mcpAuthorization:
            rules:
              - >-
                {read_rule.replace(chr(10), chr(10) + '                ')}
              - >-
                {write_rule.replace(chr(10), chr(10) + '                ')}
'''
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(config, encoding="utf-8")
    return str(config_path)


if __name__ == "__main__":
    print(render())
