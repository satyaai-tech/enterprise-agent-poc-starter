#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path


def render() -> str:
    tenant_id = os.environ.get("TENANT_ID", "11111111-2222-3333-4444-555555666666")
    issuer = os.environ.get("ISSUER", f"https://login.microsoftonline.com/{tenant_id}/v2.0")
    api_audience = os.environ.get("API_AUDIENCE", "api://agent-a-example")
    a2a_audience = os.environ.get("A2A_AUDIENCE", "api://agent-b-example")
    mcp_audience = os.environ.get("MCP_AUDIENCE", "api://banking-mock")
    api_scope = os.environ.get("API_SCOPE", "AgentA.Access")
    a2a_scope = os.environ.get("A2A_SCOPE", "AgentB.Access")
    api_client = os.environ.get("API_AUTHORIZED_CLIENT", "synthetic-agent-a")
    a2a_client = os.environ.get("A2A_AUTHORIZED_CLIENT", "synthetic-agent-a")
    mcp_client = os.environ.get("MCP_AUTHORIZED_CLIENT", "synthetic-agent-b")
    jwks_url = os.environ.get("JWKS_URL", "http://jwks-fixture:8081/.well-known/jwks.json")
    gateway_resource = os.environ.get("GATEWAY_RESOURCE", "http://localhost:18082/mcp")

    api_rule = (
        "jwt.tid == '{tenant_id}' && jwt.iat > 0 && "
        "((jwt.ver == '2.0' && jwt.azp == '{authorized_client}') || "
        "(jwt.ver == '1.0' && jwt.appid == '{authorized_client}')) && "
        "jwt.scp.split(' ').exists(scope, scope == '{expected_scope}')"
    ).format(tenant_id=tenant_id, authorized_client=api_client, expected_scope=api_scope)

    a2a_rule = (
        "jwt.tid == '{tenant_id}' && jwt.iat > 0 && "
        "((jwt.ver == '2.0' && jwt.azp == '{authorized_client}') || "
        "(jwt.ver == '1.0' && jwt.appid == '{authorized_client}')) && "
        "jwt.scp.split(' ').exists(scope, scope == '{expected_scope}')"
    ).format(tenant_id=tenant_id, authorized_client=a2a_client, expected_scope=a2a_scope)

    read_rule = (
        "jwt.tid == '{tenant_id}' && "
        "((jwt.ver == '2.0' && jwt.azp == '{authorized_client}') || "
        "(jwt.ver == '1.0' && jwt.appid == '{authorized_client}')) && "
        "jwt.scp.split(' ').exists(scope, scope == 'Banking.Read') && "
        "mcp.tool.name == 'get_account_summary'"
    ).format(tenant_id=tenant_id, authorized_client=mcp_client)

    write_rule = (
        "jwt.tid == '{tenant_id}' && "
        "((jwt.ver == '2.0' && jwt.azp == '{authorized_client}') || "
        "(jwt.ver == '1.0' && jwt.appid == '{authorized_client}')) && "
        "jwt.scp.split(' ').exists(scope, scope == 'Banking.Write') && "
        "mcp.tool.name == 'create_transfer'"
    ).format(tenant_id=tenant_id, authorized_client=mcp_client)

    config_dir = Path(os.environ.get("AG_CONFIG_PATH", "/tmp/solo-agentgateway-unified-config"))
    if config_dir.suffix.lower() in {".yaml", ".yml"}:
        config_path = config_dir
    else:
        config_path = config_dir / "config.yaml"

    config = f'''gateways:
  api-edge:
    port: 8080
    bindAddress: 0.0.0.0
    jwtAuth:
      mode: strict
      issuer: "{issuer}"
      audiences:
        - "{api_audience}"
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
        - allow: "{api_rule}"
  a2a:
    port: 8081
    bindAddress: 0.0.0.0
    jwtAuth:
      mode: optional
      issuer: "{issuer}"
      audiences:
        - "{a2a_audience}"
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
        - allow: "request.path == '/.well-known/agent-card.json'"
        - allow: "{a2a_rule}"
  mcp:
    port: 8082
    bindAddress: 0.0.0.0

routes:
  - name: agent-a-api
    gateways: [api-edge]
    matches:
      - path:
          pathPrefix: /
    backends:
      - host: "agent-a:8000"

  - name: agent-b-card
    gateways: [a2a]
    matches:
      - path:
          pathPrefix: /.well-known/agent-card.json
    backends:
      - host: "agent-b:8001"

  - name: agent-b-a2a
    gateways: [a2a]
    matches:
      - path:
          pathPrefix: /
    backends:
      - host: "agent-b:8001"

  - name: banking-health
    gateways: [mcp]
    matches:
      - path:
          pathPrefix: /healthz
    backends:
      - host: "banking-mcp:8080"

  - name: banking-mcp
    gateways: [mcp]
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
          - "{mcp_audience}"
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
                host: "http://banking-mcp:8080/mcp"
              policies:
                backendAuth:
                  passthrough: {{}}
        policies:
          mcpAuthorization:
            rules:
              - >-
                {read_rule}
              - >-
                {write_rule}
'''
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(config, encoding="utf-8")
    return str(config_path)


if __name__ == "__main__":
    print(render())
