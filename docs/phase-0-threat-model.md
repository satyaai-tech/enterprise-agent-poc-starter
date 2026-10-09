# Threat model and trust boundaries (COMPLETE)

## Status

Status: COMPLETE

This threat model is the completed Phase 0 threat model. It remains conservative, but Phase 0 closure is now signposted here.

## Trust boundaries in the target design

The repository’s architecture identifies the major trust boundaries:

1. Notebook client to northbound gateway
   - User token is presented at the edge.
   - The token must be validated before routing.

2. Kong or external validator to Agent A
   - Verified identity and policy context only.
   - Gateway or service must fail closed if validation fails or metadata is stale.

3. Agent A to A2A boundary and Agent B
   - User delegation must be explicit.
   - Agent A must not forward its own token as if it were another service’s token.
   - A2A verification is a later-phase concern and is not a Phase 0 blocker.

4. Agent B to MCP and banking mock
   - MCP tool authorization must be scoped to the user and required operation.
   - Write operations require confirmation, idempotency, and replay protection.
   - Banking write-confirmation, idempotency, and replay-control testing belongs to Phase 4 and is not a Phase 0 blocker.

## High-risk threats

### Token theft and bearer reuse

- Tokens may be captured in logs, notebooks, or debug output.
- A token that is merely reused is not the same thing as a system that has replay detection.
- A generic JWT validator can reject malformed, expired, or wrong-audience tokens, but it does not by itself detect all replay scenarios without sender-constrained tokens or an explicit replay-control design.

Controls to plan:

- no raw bearer tokens in logs,
- strict token validation at the edge,
- no cross-resource-token reuse,
- correlation ID propagation without secret disclosure,
- short-lived credentials and explicit cache handling,
- explicit replay control or sender-constrained tokens for risky flows.

### Confused deputy / wrong audience

- Agent A may obtain a token for the wrong audience and then forward it or misuse it.
- Agent B must validate its own audience and delegated scope independent of any upstream header.

Controls to plan:

- enforce exact audience matching,
- prohibit forwarding A’s token to B,
- require Entra OBO semantics for Agent B access,
- validate downstream token at the B resource server.

### Prompt injection and tool abuse

- Tool descriptions or upstream data may contain hostile instructions.
- Agents may treat tool output as trusted policy signals.

Controls to plan:

- treat tool output as untrusted data,
- enforce allowlists and least privilege,
- require explicit confirmation for state-changing operations,
- keep tool logic server-side with policy enforcement.

### Cross-user data leakage

- A user may access another user’s banking data if tool authorization is not explicit.

Controls to plan:

- user-scoped authorization checks for every banking read/write,
- explicit tool allowlists,
- resource-level authorization in the banking mock,
- deny-by-default behavior for all state-changing operations.

### Replay and duplicate writes

- A write may be retried and applied twice if not idempotent.
- Replay defense is distinct from bearer-token reuse detection.

Controls to plan:

- write confirmation before execution,
- idempotency keys,
- replay detection and audit trail,
- service-level protection even when the gateway is not the enforcement point.

## Security requirements specific to this project

The project requires fail-closed behavior when:

- token metadata is unavailable,
- key retrieval or discovery fails,
- a gateway is unavailable,
- a policy engine cannot authorize the request,
- the device or service is operating outside the expected trust domain.

## Deferred to later phases

- sanitized decoded token claims only,
- a non-reversible fingerprint of the token or assertion for evidence correlation,
- local validation of the exact Kong OSS mechanism,

- validated A2A/MCP gateway auth policy behavior,
- OBO token exchange results for the actual tenant,
- proof that no raw bearer tokens, reusable credentials, or secret material are stored in logs or evidence,
- proof that correlation IDs do not carry secret data,
- banking write confirmation, idempotency, and replay-control verification in Phase 4.

This document is complete for Phase 0 and must be extended as later phases are implemented.
