# Solo agentgateway API-edge spike

This directory contains the isolated, northbound-only validation spike for a local agentgateway v1.6.0 deployment. It intentionally stays out of the approved Phase 0 architecture and does not create or modify any Entra or OBO flows.

## Scope

- Synthetic JWT validation only
- Private Docker network only
- Local mock upstream: `mock-agent-a`
- Private JWKS fixture: `jwks-fixture`
- No live Entra calls
- No `.env` changes
- No A2A, OBO, MCP, banking, ADK, Ollama, or Macaw implementation

## Purpose

The spike tests whether a standalone agentgateway can serve as the northbound API edge for a minimal JWT-gated route using local synthetic tokens. The goal is to verify the gateway’s behavior under the same trust assumptions used by the repository’s approved security design: fail closed, exact claim checks, and an upstream that must never receive rejected requests.

## Runtime model

- `agentgateway` listens on a dynamically assigned host port defined by the test environment.
- `jwks-fixture` serves a synthetic JWK set under `/.well-known/jwks.json`.
- `mock-agent-a` is the single backend and returns a JSON success payload only when the request is authorized.
- The configuration is rendered at runtime from a temporary directory so evidence remains in pytest storage instead of source-controlled secrets.

## Official references

- agentgateway JWT authn docs: https://agentgateway.dev/docs/standalone/latest/documentation/configuration/security/jwt-authn/

This spike keeps `exp` and `nbf` in `jwtValidationOptions.requiredClaims` and validates the rest of the claim envelope locally. The observed 1.6.0 runtime behavior in this isolated stack rejects clearly expired tokens (`exp = now - 300s` or earlier) and rejects future-`nbf` tokens. Near-boundary tokens (`exp = now - 30s`) are treated as a clock-skew observation and are not treated as proof that expiration is ignored.

## Local validation

From the repo root:

```bash
uv run pytest tests/identity/test_entra_identity_validation.py tests/integration/test_solo_agentgateway_api_edge.py -q
docker compose -f experiments/solo-agentgateway/api-edge/compose.yaml config
```

## Observed runtime behavior

- A valid token is accepted and reaches the mock upstream.
- Clearly expired tokens (`exp = now - 300s` or earlier), missing, malformed, not-yet-valid, wrong audience, wrong issuer, wrong tenant, wrong scope, missing `iat`, wrong algorithm, and tampered-signature tokens are rejected with HTTP 401 or 403.
- The `mock-agent-a` upstream reports a stable request counter; rejected requests never increment it.
- Near-boundary tokens (`exp = now - 30s`) are observed separately as the clock-skew boundary case and are not used as proof that expiration is ignored.
- After the JWKS service successfully serves keys and the gateway caches them, stopping the JWKS service does not immediately fail the next valid request. That indicates in-memory JWKS caching is active and the gateway does not fail closed immediately on a remote outage.

## Remaining limitations

- This is not an Entra validation proof. It is synthetic JWT validation for the local spike only.
- It does not prove provider discovery, key rotation semantics, or enterprise-only OIDC support from Microsoft Entra.
- It does not claim replacement of the approved external authorizer architecture used in the repo’s Phase 0 design.
- The local gateway policy still depends on a trusted edge policy and safe caching assumptions; it is a proof of local behavior, not a production integration claim.
