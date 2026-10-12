# Solo A2A/OBO capability decision

This note records the exact capability boundary for the isolated `agentgateway v1.6.0` A2A/OBO spike as asserted by the local synthetic test suite and the live local Entra-backed validation.

## Phase status

Solo Phase 2 is COMPLETE.

## Verified locally

### Synthetic validation

The synthetic stack asserts the following behavior for a locally generated RSA JWT stream:

- the public Agent Card is exposed at `/.well-known/agent.json` and remains available without a bearer token
- the protected A2A route requires a valid signed JWT and exact B audience and scope checks
- the local mock Agent B independently validates RSA-signature, issuer, tenant, audience, lifetime, and delegated-scope claims before accepting the delegated message
- expired, not-yet-valid, malformed, tampered, wrong-tenant, wrong-audience, wrong-scope, missing-client, and wrong-authorization tokens fail closed
- the backend counts only protected A2A message-entry events; diagnostic and Agent Card requests are excluded from that counter
- the generated config and JWKS are created under pytest temporary storage and are not committed to source control

### Live local Entra validation

The live local Entra-backed validation passed for all required actions:

- device login succeeded
- Token A validation succeeded
- Agent A to Agent B OBO succeeded
- Token B validation succeeded
- delegated-user continuity was verified across Token A and Token B
- Solo Agentgateway enforcement accepted the valid delegated path and rejected the wrong token path
- Agent B defense-in-depth validation succeeded
- Token A was rejected at the Agent B boundary
- successful A2A delivery completed
- automatic Docker cleanup ran after the validation flow

Canonical evidence file: [evidence/solo-phase-2/solo-a2a-live-20261012T030839498195Z-7a4b163f60b4.json](../evidence/solo-phase-2/solo-a2a-live-20261012T030839498195Z-7a4b163f60b4.json)

## Not claimed as production proof

This local Solo validation is POC evidence only. It does not certify production readiness, production key rotation, high availability, or enterprise deployment suitability.

## Security decision

The validated design keeps responsibilities separate:

- gateway: enforce route-level JWT policy and pass the validated token to the backend
- Agent A: perform the OBO exchange in application code for the delegated Agent B call
- Agent B: independently revalidate the token before processing the delegated message
- evidence: store only sanitized status booleans and non-sensitive metadata, never raw token claims or user identity values

This matches the approved Phase 0 boundary: the gateway enforces the route policy it is trusted to enforce, the application performs the OBO exchange, and the service re-validates identity before acting on delegated work.
