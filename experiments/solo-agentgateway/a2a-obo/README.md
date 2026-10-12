# Solo agentgateway A2A/OBO spike

This directory contains the isolated A2A/OBO validation spike for a local standalone agentgateway v1.6.0 deployment. It intentionally stays out of the approved Phase 0 architecture and does not make or store live Entra calls or real Microsoft tokens.

## Scope

- Synthetic Entra-like JWT validation for the Agent B audience and delegated scope
- Host-side OBO simulation for the Agent A -> Agent B hop
- Public Agent Card route plus protected A2A message route
- Private Docker network only
- Local mock Agent B backend
- Private JWKS fixture
- No live Entra, `.env`, banking, ADK, Ollama, or Macaw implementation

## Purpose

The spike validates the boundary semantics that matter for a later A2A/OBO implementation:

- the gateway enforces a B audience and delegated scope
- the host-side middle tier is responsible for an OBO exchange or equivalent token minting behavior
- a direct Agent A token is rejected when presented to Agent B
- invalid, expired, tampered, and wrong-scope tokens fail closed
- the public Agent Card route remains accessible while the protected A2A message route requires a valid delegated token

## Runtime model

- `agentgateway` listens on a dynamically assigned host port defined by the test environment.
- `jwks-fixture` serves synthetic JWKs at `/.well-known/jwks.json`.
- `mock-agent-b` exposes a public Agent Card and a protected A2A message endpoint.
- The configuration is rendered at runtime from a temporary directory so evidence remains in pytest storage rather than committed to source control.

## Local validation

From the repo root:

```bash
uv run pytest tests/integration/test_solo_agentgateway_a2a_obo.py -q
docker compose -f experiments/solo-agentgateway/a2a-obo/compose.yaml config
```

## Security notes

- The gateway is configured to reject tokens with the wrong audience, wrong delegated scope, expired lifetime, invalid signature, or missing required claims.
- The gateway does not preserve the raw JWT for upstream processing; the backend revalidates the bearer token against its own JWKS before accepting a delegated call.
- No exact Microsoft Entra token, raw JWT, secret, or client credential is stored in the repository.
