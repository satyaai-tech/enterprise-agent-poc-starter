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

This unified slice is the Slice 5A happy path. It keeps the synthetic JWT trust
chain private and local: a private JWKS fixture supplies the public keys, Agent A
attaches Token B for the protected A2A route, and Agent B uses Token C for the
read-only MCP balance lookup. The private key never enters the app containers.

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

## Guarded live Entra validation

The synthetic profile above remains the safe default. The guarded live path is intentionally opt-in and starts from `experiments/solo-agentgateway/unified/live_unified_obo.py`:

```bash
PYTHONPATH="$PWD" uv run python experiments/solo-agentgateway/unified/live_unified_obo.py --live
```

This path loads the local `.env` values without printing secrets, renders the Agent Gateway config, starts the unified Compose stack automatically, waits for the protected A2A and MCP endpoints, validates the Token A -> Token B -> Token C chain, and then tears the stack down in cleanup. The explicit `compose.live.yaml` file is kept separate from the default synthetic `compose.yaml` so the local happy path does not change under default automation.

## Persistent live stack for Jupyter

Agent A and Agent B each read their own client secret from an absolute, external,
read-only file. Set `ENTRA_AGENT_A_CLIENT_SECRET_FILE`,
`ENTRA_AGENT_B_CLIENT_SECRET_FILE`, `BANKING_TEST_USER_OID`, and the remaining
Entra values in the ignored `.env`. Keep `POC_LOG_RAW_USER_ID=true` only for
local POC diagnostics.

Start the containers and leave them running:

```bash
PYTHONPATH="$PWD" uv run python \
  experiments/solo-agentgateway/unified/live_unified_obo.py \
  --start-only
```

Then start Jupyter in a second terminal and run
`notebooks/phase-5-slice-5b-read-only-demo.ipynb`. The notebook performs the
device-code sign-in, holds Token A only, and calls the API listener at
`http://127.0.0.1:18080`. Agent A exchanges Token A for Token B and Agent B
exchanges Token B for Token C inside their request-scoped runtime boundaries.

Stop the persistent stack afterward:

```bash
PYTHONPATH="$PWD" uv run python \
  experiments/solo-agentgateway/unified/live_unified_obo.py \
  --stop
```
