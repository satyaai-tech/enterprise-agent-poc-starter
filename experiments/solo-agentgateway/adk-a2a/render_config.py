#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path


def render() -> str:
    config_path = Path(
        os.environ.get("AG_CONFIG_PATH", "/tmp/solo-agentgateway-adk-a2a-config")
    )
    if config_path.exists() and config_path.is_dir():
        config_path = config_path / "config.yaml"
    elif config_path.suffix.lower() not in {".yaml", ".yml"} and not config_path.name.endswith(".yaml"):
        config_path = config_path / "config.yaml"
    public_url = os.environ.get("A2A_PUBLIC_URL", "http://127.0.0.1:18081")
    config = f'''gateways:
  default:
    port: 8080
    bindAddress: 0.0.0.0

routes:
  - name: public-agent-card
    matches:
      - path:
          pathPrefix: /.well-known/agent-card.json
    backends:
      - host: "agent-b:8001"

  - name: public-a2a-rpc
    matches:
      - path:
          pathPrefix: /
    backends:
      - host: "agent-b:8001"

# Public Agent B agent card is advertised at {public_url} by the backend service.
'''
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(config, encoding="utf-8")
    return str(config_path)


if __name__ == "__main__":
    print(render())
