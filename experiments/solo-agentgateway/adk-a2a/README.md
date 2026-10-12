# Solo ADK A2A routing slice

This profile keeps the direct local ADK Agent B service private and exposes only the Solo agentgateway A2A boundary on the host. It is intentionally limited to routing and connectivity.

## Topology

- Host: `127.0.0.1:18081` via Solo agentgateway
- Private backend: `agent-b:8001` on the Compose network
- Direct debug path: `http://127.0.0.1:8001` remains available when running locally without Docker
- No Entra, JWT, OBO, or MCP policy is enabled in this slice

## Runtime notes

- the `agent-b` container binds to `0.0.0.0:8001`
- the backend advertises the public gateway URL via `A2A_PUBLIC_URL`
- the Solo gateway routes both the public card and the A2A message endpoint to the private backend

## Validation

```bash
uv run pytest tests/integration/test_solo_agentgateway_adk_a2a.py -q
docker compose -f experiments/solo-agentgateway/adk-a2a/compose.yaml config
```
