# Native agentgateway JWT validation versus the approved external authorizer path

This note captures the capability gap observed in the isolated Solo agentgateway spike.

## What the spike proves

The local agentgateway v1.6.0 stack proves that:

- a standalone gateway can read a bearer JWT,
- verify a locally served JWKS public key,
- enforce exact issuer, audience, tenant, scope, and authorized-client checks,
- reject malformed or tampered tokens,
- and route only authorized traffic to an upstream mock service.

The implementation uses synthetic RSA tokens and a private JWKS fixture. The configuration enforces exact membership checks such as `AgentA.Access` and rejects `AgentA.AccessExtra` because it is not the same exact scope value.

## What the spike does not prove

This is intentionally not a claim that agentgateway replaces the repository’s approved Entra validation design.

The local spike does not validate the exact Microsoft Entra behavior for:

- provider discovery and tenant metadata,
- production-grade key rotation and JWKS lifecycle handling,
- Entra-specific issuer and authority semantics,
- OIDC/OBO or delegated-identity patterns,
- enterprise-only requirements or support tiers,
- or the repository’s external authorizer + Kong northbound architecture.

## Observed capability gap

The observed runtime behavior is a capability gap: the gateway can enforce exact JWT policy for a synthetic token stream, but the runtime also shows a local JWKS cache can continue accepting valid signed tokens after the JWKS service is stopped. This is useful for local validation, but it is not equivalent to proving the full Microsoft Entra validation lifecycle or the production authorization design used by the repo.

For this repository, the relevant conclusion is therefore:

- native gateway validation can be evaluated locally,
- synthetic JWT checks can be satisfied in the isolated northbound edge,
- but the native path is not a substitute for the approved external authorizer path unless a pinned production-scale Entra validation design is separately proven.

The repo’s approved architecture remains the stronger and more explicit design: enforce identity and authorization at the gateway/service boundary before forwarding to Agent A, and keep the verification evidence explicit and scoped to the exact token model being used.

## Remaining limitation

The local gateway spike should be treated as a constrained local validation exercise, not as an enterprise token-validation claim or a production recommendation.
