# Microsoft Entra OBO registration and validation checklist (PENDING)

## Status

Status: PENDING

This checklist captures the exact validation work still required before any OBO-based implementation can be treated as real evidence.

## Required registration model

For the target design, the project must define and confirm the following before implementation:

- one test tenant dedicated to the local proof
- one test user with no real data access
- separate app registrations for Agent A and Agent B
- explicit Application ID URI and delegated scopes for each protected API
- whether the OBO middle tier operates as a confidential client using a secret or certificate
- which app registration is allowed to request the downstream token for B
- whether the design is single-tenant for the initial POC

## Microsoft official authoritative flow

Primary-source references:

- Microsoft Entra OBO flow: https://learn.microsoft.com/entra/identity-platform/v2-oauth2-on-behalf-of-flow
- Access token validation guidance: https://learn.microsoft.com/entra/identity-platform/access-tokens
- Claims validation guidance: https://learn.microsoft.com/entra/identity-platform/claims-validation

Key requirements from the official flow:

- The incoming token must have an audience that matches the app performing the OBO request.
- The middle-tier app must present the incoming user assertion to the token endpoint using the OBO grant.
- The downstream request must request the correct scope for the downstream API.
- Agent B must validate the token for its own audience and required delegated scope.

## Operational checklist

### Tenant inputs required from the operator

- Tenant ID
- User account used for test sign-in
- App registration IDs for A and B
- Application ID URIs for A and B
- Delegated scope names for A and B
- Whether the middle tier uses a client secret or certificate
- Consent or admin-grant state for the required delegated permissions

### Required validation tests

- success case: valid A token, valid A-to-B OBO exchange, valid B token
- failure case: A token forwarded directly to B
- failure case: wrong audience on the incoming assertion
- failure case: missing delegated scope on the downstream request
- failure case: wrong tenant or wrong issuer
- failure case: expired or malformed assertion
- failure case: app-only token where user delegation is required
- failure case: tampered assertion or token replay

### Required evidence to collect

- sanitized decoded claims for the incoming token
- sanitized decoded claims for the exchanged B token
- a non-reversible fingerprint of the assertion and token metadata used in the OBO request
- the app registration IDs used in the flow
- success and failure results for each test case
- explicit record of whether the project accepted the OBO design or rejected it and moved to a fallback

Important: do not store the exact OBO assertion, access token, client secret, or any reusable credential in the repo or in evidence. Evidence may contain sanitized claim maps and a non-reversible token fingerprint only.

## Hard rule

Do not forward Agent A’s access token directly to Agent B and call it OBO. This is not a valid OBO design.

This checklist remains pending until the real tenant and app registrations are available.
