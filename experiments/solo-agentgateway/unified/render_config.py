#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path


def render() -> str:
    config_dir = Path(
        os.environ.get("AG_CONFIG_PATH", "/tmp/solo-agentgateway-unified-config")
    )
    if config_dir.suffix.lower() in {".yaml", ".yml"}:
        config_path = config_dir
    else:
        config_path = config_dir / "config.yaml"

    config = '''gateways:
  api-edge:
    port: 8080
    bindAddress: 0.0.0.0
  a2a:
    port: 8081
    bindAddress: 0.0.0.0
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
    backends:
      - mcp:
          targets:
            - name: banking
              mcp:
                host: "http://banking-mcp:8080/mcp"
              policies:
                backendAuth:
                  passthrough: {}
'''
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(config, encoding="utf-8")
    return str(config_path)


if __name__ == "__main__":
    print(render())
