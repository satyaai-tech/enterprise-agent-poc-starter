# Architecture

## Scope

This document defines a target architecture to test. It does not certify component support or interoperability.

## Context and trust boundaries

```text
┌────────────────────────── Mac host ──────────────────────────┐
│ Jupyter Notebook                                            │
│   │ user access token                                       │
│   ▼                                                         │
│ published Docker port                                       │
│   │                                                         │
│ Agent A (Google ADK) ── local API ── Ollama                 │
│   │ delegated request / proposed OBO token                  │
│   ▼                                                         │
│ Agent B (Google ADK)                                        │
│   │ MCP tool request                                        │
│   ▼                                                         │
│ local MCP banking mock server (read/write)                   │
└───┼──────────────────────────────────────────────────────────┘
    │ host.docker.internal whenever a container calls the host
┌───▼──────────────────── Docker Desktop ──────────────────────┐
│ Kong OSS API gateway                                        │
│ open-source Agent Gateway: A2A boundary                      │
│ Agent Gateway: MCP boundary                                  │
└──────────────────────────────────────────────────────────────┘
```

Logical flow, regardless of final process placement:

1. The notebook obtains a test-user access token intended for the API exposed through Kong.
2. Kong validates the token and routes only an accepted request to Agent A.
3. Agent A performs local reasoning through Ollama and decides whether to delegate.
4. Agent A requests or presents a downstream token using the Entra OBO design, subject to Phase 0 feasibility.
5. The A2A gateway enforces the selected protocol, authentication, routing, and policy before Agent B.
6. Agent B reasons locally, then asks for a banking tool through an MCP gateway.
7. The MCP gateway enforces tool allowlists and authorization context before the banking mock.
8. A response returns through the same boundaries with one correlation identifier.

## Component responsibilities

| Component | Intended responsibility | Must not be assumed |
|---|---|---|
| Notebook | Interactive test client and token acquisition trigger | Secure production client or confidential-client secret storage |
| Kong OSS | Northbound routing, TLS in later hardening, token enforcement if a verified OSS path exists | Native Microsoft Entra OIDC support or enterprise-only plugin availability |
| Agent A | User-facing orchestration and delegation to B | Autonomous identity, OBO correctness, or unrestricted tool access |
| Ollama | Local model inference for Agent A (and optionally B) | Authorization decisions or prompt-injection protection |
| A2A gateway | Protocol boundary, routing, policy, and observability if selected software proves these | Any particular project's capability until versioned tests pass |
| Agent B | Banking-domain reasoning and MCP client behavior | Trust in unsigned upstream claims or direct database access |
| MCP gateway | Tool discovery/routing and policy if verified | User delegation, write authorization, or stable semantics without testing |
| Banking mock | Deterministic fake balances, transactions, and write operations | Real banking behavior, persistence guarantees, or use of real data |
| Entra ID | Test user, app registrations, consent, token issuance, and proposed OBO | A generic “agent identity blueprint” or support beyond documented OAuth behavior |

## Identity model to test

- One Entra tenant and one dedicated test user.
- Separate app registrations for Agent A's protected API and Agent B's protected API.
- Explicit application ID URI and delegated scopes for each protected API.
- A public-client or device-code-capable test client only if tenant policy permits it; otherwise use an approved developer-client pattern.
- Agent A is a confidential middle tier only if OBO requires it and secrets/certificates can be handled safely.
- OBO must preserve the user delegation chain; it is not a replacement for app-only authorization.
- Agent B validates its own audience, issuer, signature, lifetime, tenant, and required delegated scope.
- Downstream tool permissions are derived from verified identity context and local policy, not natural-language claims.

See [entra-identity.md](entra-identity.md) for registration details and unresolved questions.

## Authorization model

Use deny-by-default policy at every boundary:

- Kong: accepted issuer/tenant, exact audience, required user scope, supported algorithm, valid lifetime.
- A2A gateway: authenticated caller, allowed target agent, allowed task/operation, bounded payload.
- Agent B: downstream token checks repeated; never trust gateway headers without a protected trust mechanism.
- MCP gateway: explicit read/write tool allowlists, user and caller context, schema limits, and confirmation/idempotency for writes.
- Banking mock: server-side authorization check even if the gateway already checked.

## Observability and evidence

Generate one opaque correlation ID at the edge and propagate it through all hops. Logs may include tenant, subject hash, client/app ID, audience result, scope decision, route, tool name, result class, and timing. Logs must not include tokens, secrets, raw authorization headers, or sensitive banking payloads.

Keep redacted proof in `evidence/` organized by phase. Evidence should name component versions and configuration hashes so results can be reproduced.

## Deliberate exclusions

- Macaw is deferred.
- Production deployment, high availability, real banking integrations, and real customer data.
- A generalized enterprise agent-identity blueprint.
- Claims that Kong OSS includes Microsoft Entra OIDC integration.
- Claims that an unspecified Agent Gateway implements A2A, MCP, OBO, or the required policy semantics.

