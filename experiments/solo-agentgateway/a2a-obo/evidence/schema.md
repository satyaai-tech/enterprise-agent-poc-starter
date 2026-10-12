# Solo A2A/OBO token and route schema

This directory intentionally stores only synthetic, local-only validation artifacts. The gateway must keep the public Agent Card route open while the protected A2A entrypoints require a valid delegated token.

## Public route

- path: `/.well-known/agent.json`
- method: `GET`
- auth: not required

## Protected routes

- path prefixes: `/a2a`, `/__debug`
- method: `POST` for A2A send-message requests
- auth: bearer token required
- request contract: JSON-RPC 2.0 with a `message` payload that includes a message id and a user role

## Gateway validation requirements

The validated bearer token must satisfy all of the following before the request is forwarded upstream:

- issuer matches the local synthetic tenant metadata
- audience matches `api://agent-b-example`
- tenant id matches the synthetic tenant id
- delegated scope contains `AgentB.Access`
- `azp` is present for v2 tokens, or `appid` for v1 tokens
- `exp`, `nbf`, `iat`, and `ver` are present and valid
- signature validates against the local JWKS fixture

## Fail-closed behavior

- a missing or malformed token is rejected with `401` or `403`
- an expired, not-yet-valid, wrong-issuer, wrong-audience, or wrong-scope token is rejected before reaching the backend
- backend validation re-checks the token independently before processing the protected message
- a missing or broken JWKS causes immediate rejection until the key material is restored

## Synthetic-only evidence

- tokens are generated locally in tests only
- no live Entra, tenant secret, or client credential data is stored in this repo
- debug evidence never logs raw headers, secrets, or complete JWTs
