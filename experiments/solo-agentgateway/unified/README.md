# Unified Solo gateway profile

This Phase 5 profile combines the three previously isolated gateway roles into
one physical Solo agentgateway process with three logical listeners.

| Host default | Container listener | Route | Private backend |
| --- | --- | --- | --- |
| `127.0.0.1:18080` | `8080` | ADK API and development UI | `agent-a:8000` |
| `127.0.0.1:18081` | `8081` | Agent Card and A2A HTTP | `agent-b:8001` |
| `127.0.0.1:18082` | `8082` | MCP HTTP | `banking-mcp:8080` |

Only the unified gateway publishes host ports. Agent A, Agent B, and Banking
MCP stay private on the Compose network. Agent A calls Agent B at
`http://agentgateway:8081`, so no loopback address is used between containers.

## Current boundary

This first unified slice proves process consolidation and routing. It does not
replace the authenticated isolated evidence. Entra JWT/OBO and the proven MCP
authorization rules must be layered into this profile in a subsequent focused
change before it is treated as the secured end-to-end runtime.

## Run

```bash
export AG_CONFIG_PATH=/tmp/solo-agentgateway-unified-config
python3 experiments/solo-agentgateway/unified/render_config.py
docker compose -f experiments/solo-agentgateway/unified/compose.yaml up -d --build --wait
```

Open the Agent A UI through Solo at `http://127.0.0.1:18080/dev-ui`.

Check the other two listeners:

```bash
curl http://127.0.0.1:18081/.well-known/agent-card.json
curl http://127.0.0.1:18082/healthz
```

Stop the profile:

```bash
docker compose -f experiments/solo-agentgateway/unified/compose.yaml down -v --remove-orphans
```
