# Microsoft Entra Identity Design

This is a proposed test-tenant design. Confirm every field against current Microsoft documentation and tenant policy before provisioning.

## Principals and registrations

| Item | Purpose | Proposed configuration to verify |
|---|---|---|
| Test user | Delegated user context | Dedicated non-privileged account with no real data |
| Notebook client | Initiates interactive test | Approved public-client/device-code pattern, or another tenant-approved developer client |
| Agent A registration | Protected northbound API and OBO middle tier | Application ID URI plus delegated scope such as `AgentA.Access`; confidential credential only if required for OBO |
| Agent B registration | Protected downstream API | Separate Application ID URI plus delegated scope such as `AgentB.Access` |

Names above are illustrative, not commands or final identifiers.

## Proposed token sequence

1. The notebook obtains a user-delegated access token whose audience is Agent A's API and whose scopes include Agent A access.
2. The northbound validation layer validates the signed JWT and required claims before Agent A.
3. Agent A, acting as the permitted confidential middle tier, submits the incoming user assertion to Entra's OBO flow and requests Agent B's delegated scope.
4. Entra returns a B-audience token only if registration, credentials, scopes, consent, tenant policy, and the incoming assertion allow it.
5. The A2A boundary and Agent B validate the properties relevant to their responsibility. Agent B must independently enforce its expected audience and scope.

Do not forward Agent A's token to Agent B and call it OBO. Do not substitute client credentials for user delegation. Do not infer user identity from notebook input or model text.

## Validation checklist

At each resource server, validate using maintained libraries or a verified gateway feature:

- Signature using trusted Entra metadata and permitted algorithms.
- Issuer and tenant exactly as designed; decide explicitly whether the API is single-tenant.
- Audience for that resource, not just a syntactically valid JWT.
- Lifetime claims with bounded clock skew.
- Required delegated scope (`scp`) or application role (`roles`), according to the allowed grant type.
- Authorized client/application identifier where the design restricts calling clients.
- Subject/user context and any policy-relevant claims.
- Key rotation and metadata-cache failure behavior.

Never authorize solely because a token is signed by Entra.

## Kong OSS verification gate

Do **not** claim that Kong OSS provides Microsoft Entra OIDC integration. Before implementation, test the exact pinned OSS release and available plugins against an actual test-tenant token. A generic JWT plugin may have issuer/key-management, claim-mapping, discovery, algorithm, or edition limitations that prevent the required design.

Document one outcome:

1. **Verified:** the exact OSS mechanism validates signature and every required claim, with passing negative tests; or
2. **Not sufficient:** choose an approved alternative and update the trust-boundary diagram; or
3. **Unknown:** stop protected-route implementation until resolved.

Any community plugin requires explicit review of source, maintenance, license, supply chain, failure mode, and compatibility. “Installable” does not mean acceptable.

## OBO verification gate

Confirm with a minimal non-agent spike before adding A2A behavior:

- Which client owns the confidential credential or certificate.
- Agent A and Agent B application ID URIs and exposed delegated scopes.
- Pre-authorized clients, delegated permissions, and admin/user consent requirements.
- Token endpoint authority and tenant behavior.
- Incoming assertion audience and grant requirements.
- Conditional Access, MFA, claims challenges, and whether the developer flow can satisfy them.
- Error handling without fallback to client credentials or a broader identity.
- Whether the chosen libraries cache tokens safely without logging them.

## Secrets and evidence

- Prefer short-lived credentials or certificates where practical for a local POC.
- Keep values in a developer secret store or process environment excluded from Git.
- Redact JWTs in screenshots and logs. Store decoded claim names and sanitized values, not reusable tokens.
- Never add tenant secrets to `.env.example`; list variable names only when implementation begins.
- Remove test credentials and revoke grants when the POC is retired.

## Open decisions

- Single-tenant versus multitenant (single-tenant is the safer POC default).
- Approved notebook authentication flow under tenant policy.
- Secret versus certificate for the OBO middle tier.
- Exact audiences and delegated scope names.
- Whether Kong remains the validation enforcement point or routes through a verified external authorizer.
- How user identity and scopes are bound to MCP tool authorization without trusting mutable headers.

