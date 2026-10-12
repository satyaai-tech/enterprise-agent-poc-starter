# Solo A2A/OBO capability decision

This note records the exact capability boundary for the isolated `agentgateway v1.6.0` A2A/OBO spike as asserted by the local synthetic test suite.

## Verified locally

The synthetic stack asserts the following behavior for a locally generated RSA JWT stream:

- the public Agent Card is exposed at `/.well-known/agent.json` and remains available without a bearer token
- the protected A2A route requires a valid signed JWT and exact B audience and scope checks
- the local mock Agent B independently validates RSA-signature, issuer, tenant, audience, lifetime, and delegated-scope claims before accepting the delegated message
- expired, not-yet-valid, malformed, tampered, wrong-tenant, wrong-audience, wrong-scope, missing-client, and wrong-authorization tokens fail closed
- the backend counts only protected A2A message-entry events; diagnostic and Agent Card requests are excluded from that counter
- the generated config and JWKS are created under pytest temporary storage and are not committed to source control

## Not claimed as production proof

This experiment is not a claim that agentgateway v1.6.0 replaces the repository’s approved Entra validation design or the external authorizer path. The local results do not prove live Microsoft Entra discovery, production key rotation, or live OBO exchange semantics.

## Security decision

The validated design keeps responsibilities separate:

- gateway: enforce route-level JWT policy and pass the validated token to the backend
- Agent B: independently revalidate the token before processing the delegated message
- evidence: store only sanitized status booleans and non-sensitive metadata, never raw token claims or user identity values

This matches the approved Phase 0 boundary: the gateway enforces the route policy it is trusted to enforce, and the service re-validates identity before acting on delegated work.
