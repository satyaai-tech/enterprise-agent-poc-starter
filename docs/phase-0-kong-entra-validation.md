# Kong OSS Entra-validation decision and fallback options (PENDING)

## Status

Status: PENDING

The repository design requires the northbound validation path to validate Microsoft Entra-issued tokens before routing to Agent A. Kong OSS is a candidate, but the exact behavior for this project remains unverified.

## Official evidence currently available

Official Kong source material and plugin docs:

- Kong releases: https://github.com/Kong/kong/releases
- Kong JWT plugin docs: https://developer.konghq.com/plugins/jwt/
- Kong OpenID Connect plugin docs: https://developer.konghq.com/plugins/openid-connect/

The official Kong OpenID Connect plugin page contains page metadata with `algolia:tier` = `enterprise`. That is the official source statement that the OpenID Connect plugin is Enterprise-only and is not a Kong OSS solution. The repository must therefore not treat the Kong OpenID Connect plugin as a valid Kong OSS path.

The Kong JWT plugin is a separate capability and must be evaluated on its own. It is a generic JWT validator; it does not by itself provide Microsoft Entra discovery, tenant-aware issuer logic, automatic JWKS refresh, or a complete Entra-specific validation policy.

## Decision

### Selected design decision

- Kong Gateway OSS 3.9.3 remains the required northbound routing gateway.
- The proposed external authorizer performs complete Entra JWT validation before a request reaches Agent A.
- The external authorizer implementation and all local test results remain Pending.

### Current stance

- Kong OpenID Connect plugin: not a Kong OSS solution; enterprise-only
- Kong JWT plugin: Not Sufficient By Itself for the required Entra validation
- Not Verified for this design
- Not eligible for a “works” claim until a tenant-backed local validation spike proves the required Entra checks

### Operational interpretation

The Kong OSS JWT plugin is limited in the ways that matter here:

- it does not provide Microsoft Entra discovery or a tenant-aware OIDC metadata flow by itself
- it does not automatically replace or refresh Entra JWKS material in the way an Entra-first implementation requires unless the operator configures and maintains that logic correctly
- it does not automatically assert the correct Microsoft Entra `iss`, `aud`, `tid`, or `scp`/`roles` semantics for a specific app registration and API
- it does not validate all required tenant, audience, and delegated-scope rules without explicit configuration and verification
- it does not by itself guarantee replay rejection for every token reuse scenario; a generic JWT validator does not provide replay protection unless sender-constrained tokens or an explicit replay-control design is added

For this project, the required checks remain:

- `iss` exactly matches the configured Microsoft Entra tenant issuer
- `aud` matches the protected API audience for this app registration
- `tid` matches the target tenant and is bound to the issuer context
- `scp` or `roles` is checked for the specific delegated or app permission required
- `exp`, `nbf`, and `iat` semantics are validated correctly
- signature validation uses the correct Entra signing key material or validated JWKS flow
- invalid, expired, mismatched-tenant, and wrong-scope tokens fail closed

## Fallback options if Kong OSS is insufficient

### Option A — trusted external authorizer in front of Agent A

Use a small, explicit validation service that:

- fetches Entra metadata and JWKS from the configured tenant metadata
- validates the JWT signature and required claims
- checks issuer, tenant, audience, and delegated scope
- emits only an opaque correlation ID and approved identity metadata after validation
- fails closed when metadata, signature checks, or policy decisions fail

This is the safest fallback for Phase 0 because it makes the validation boundary explicit and separate from the application logic.

### Option B — verified community plugin or gateway extension

A plugin or extension may be considered only if it is:

- version-pinned,
- documented by primary sources,
- maintained and clearly scoped,
- tested against the exact Entra token profile,
- accepted as the enforcement boundary by the project owner,
- and validated with local negative tests.

This is not acceptable based on installation alone.

### Option C — different gateway or gateway edition

A different gateway or gateway edition may be chosen only if it demonstrates the same Entra validation requirements and the project documents the reason for the change. This decision must be explicit and evidence-led, not assumed.

## Unresolved risk

The remaining unresolved risk is whether the proposed external authorizer can perform the complete Entra validation policy and integrate with Kong without creating a bypass. This remains Pending local verification.
