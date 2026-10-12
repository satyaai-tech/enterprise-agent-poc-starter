# Solo agentgateway MCP spike

This directory contains the isolated synthetic validation spike for a local standalone agentgateway v1.6.0 deployment at the MCP boundary.

## Scope

- Synthetic JWT validation only
- Local Docker private network only
- Local mock banking backend
- JWKS fixture for testing token verification
- No live Entra calls
- No OBO, A2A, or production claims

## Purpose

This spike verifies a minimal MCP gateway contract: a protected route accepts a valid delegated token, rejects missing or wrong scope tokens, and enforces tool-level allow lists before forwarding to the mock banking backend.

## Runtime model

- `agentgateway` receives requests on a host-assigned port.
- `jwks-fixture` publishes a synthetic JWK set at `/.well-known/jwks.json`.
- `mock-banking` performs server-side scope validation and tool allowlist enforcement.
- The config is rendered from a temporary directory for the local pytest run.

## Local validation

```bash
uv run pytest tests/integration/test_solo_agentgateway_mcp.py -q
docker compose -f experiments/solo-agentgateway/mcp/compose.yaml config
```
