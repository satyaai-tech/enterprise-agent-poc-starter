# Phase 0 decision record (PENDING)

This document is intentionally a planning artifact, not a completion signoff. It records the current evidence base, the current candidate set, and the exact blockers that remain before any implementation or deployment work may proceed.

## Scope and status

Status: PENDING

This repository remains documentation-only and no application code or deployment configuration is created in this Phase 0 pass. The decisions below are provisional and must be validated in the user tenant and local Docker environment before any implementation begins.

## Official release check summary

The versions below were rechecked directly against the project official release or package sources on 2026-10-08.

| Project | Official source | Release tag | Release date (UTC) | Date checked |
|---|---|---|---|---|
| Kong Gateway | https://github.com/Kong/kong/releases | 3.9.3 | 2026-06-17T06:02:19Z | 2026-10-08 |
| Google ADK | https://github.com/google/adk-python/releases | v2.11.0 | 2026-10-02T00:44:26Z | 2026-10-08 |
| Ollama | https://github.com/ollama/ollama/releases | v0.40.1 | 2026-10-07T23:22:59Z | 2026-10-08 |
| A2A | https://github.com/a2aproject/A2A/releases | v1.0.1 | 2026-05-28T11:34:36Z | 2026-10-08 |
| MCP spec | https://github.com/modelcontextprotocol/modelcontextprotocol/releases | 2026-07-28 | 2026-07-28T16:47:49Z | 2026-10-08 |
| agentgateway | https://github.com/agentgateway/agentgateway/releases | v1.6.0 | 2026-10-02T16:26:26Z | 2026-10-08 |

## Current evaluation recommendation

The current Phase 0 recommendation is:

- Northbound routing gateway: Kong Gateway OSS 3.9.3 remains the required northbound routing gateway.
- Entra validation design: a trusted external authorizer is the proposed design for complete Entra JWT validation before a request reaches Agent A. Implementation and local verification remain Pending.
- A2A gateway evaluation candidate: agentgateway/agentgateway v1.6.0, proposed as a separate deployment boundary for A2A traffic.
- MCP gateway evaluation candidate: agentgateway/agentgateway v1.6.0, proposed as a separate deployment boundary for MCP traffic.
- Runtime candidates: Google ADK v2.11.0 and Ollama v0.40.1
- Protocol references: A2A v1.0.1 and MCP 2026-07-28

This recommendation is an evaluation candidate list, not a Verified deployment design. It remains Pending until local tenant and Docker validation is complete.

## Candidate comparison

### 1) Kong Gateway OSS versus the official Kong OIDC plugin

Official sources:

- Kong JWT plugin: https://developer.konghq.com/plugins/jwt/
- Kong OpenID Connect plugin: https://developer.konghq.com/plugins/openid-connect/
- Kong release list: https://github.com/Kong/kong/releases

Relevant findings:

- The official Kong OpenID Connect plugin page declares `algolia:tier` = `enterprise` in the page metadata. This means the official OpenID Connect plugin is not presented as an OSS solution and must not be treated as a Kong OSS path for this project.
- Kong Gateway OSS 3.9.3 remains the required northbound routing gateway.
- The bundled Kong JWT plugin is Not Sufficient By Itself for the required Entra validation. It is a generic JWT verifier and is not an Entra discovery or OIDC integration layer. Its documented scope is token validation, not automatic discovery of Microsoft Entra metadata, tenant-specific issuer rules, or tenant-specific audience checks.
- For Microsoft Entra, an implementation still must validate the JWT signature, issuer, audience, tenant, and delegated scope claims. The official Microsoft Entra guidance also requires validating the appropriate `aud`, `iss`, `tid`, and `scp`/`roles` claims against the actual app registration and API.

This project therefore keeps:

- Kong OIDC plugin: not a Kong OSS solution, not eligible as an OSS path
- Kong JWT plugin: Not Sufficient By Itself for the required Entra validation
- Kong as northbound routing layer: required, but the complete Entra validation remains in a separate external authorizer design and is Pending

### 2) agentgateway/agentgateway as a concrete candidate

Official sources:

- Repository: https://github.com/agentgateway/agentgateway
- Releases: https://github.com/agentgateway/agentgateway/releases
- Homepage: https://agentgateway.dev
- README: https://raw.githubusercontent.com/agentgateway/agentgateway/main/README.md

Relevant findings from the official project:

- The project describes itself as an open source proxy for AI-native protocols, including MCP and A2A.
- The README lists specific gateway roles: `MCP Gateway` and `A2A Gateway`.
- The README also lists `Auth (JWT, API keys, OAuth)`, `fine-grained RBAC with CEL policy engine`, `rate limiting`, `TLS`, and `OpenTelemetry metrics/logs/tracing` as core capabilities.
- The repository license is Apache 2.0 and the project is a Linux Foundation effort.
- The project is active and under active development, with a current release tag of `v1.6.0` released on 2026-10-02.

Comparison to a credible alternative:

| Candidate | Official source | License | Maintenance status | Standalone / Docker / macOS suitability | A2A and MCP documentation | Auth hooks and policy | Observability |
|---|---|---|---|---|---|---|---|
| agentgateway/agentgateway | https://github.com/agentgateway/agentgateway | Apache 2.0 | Active development; current release v1.6.0 | Official README documents standalone quickstart and flat YAML configuration; no native macOS claim, so local Docker Desktop validation remains required | README explicitly names both `MCP Gateway` and `A2A Gateway` | `Auth (JWT, API keys, OAuth)` and CEL RBAC policy engine documented | OpenTelemetry metrics/logs/tracing documented |
| Kong Gateway OSS | https://github.com/Kong/kong | Apache 2.0 | Mature, active, maintained | OSS gateway can be run locally in a Dockerized environment and is suitable for local evaluation, but the OpenID Connect plugin is not OSS and the JWT plugin is generic | Kong exposes MCP/A2A-adjacent gateway capabilities but not a single official A2A/MCP selection as an OSS product claim | JWT plugin is generic; OIDC plugin is enterprise-flagged | Kong has its own observability and metrics ecosystem, but the exact Entra policy behavior remains unproven |

Decision:

- Select agentgateway v1.6.0 as the evaluation candidate for two separate deployments: an A2A gateway boundary and an MCP gateway boundary.
- Keep Kong OSS as the required northbound routing gateway layer.
- Keep the external authorizer as the proposed Entra validation design before a request reaches Agent A.
- Do not mark either deployment as locally verified. Both A2A and MCP agentgateway deployments remain Locally Unverified.

### 3) Google ADK and Ollama runtime candidates

Official sources:

- Google ADK repo: https://github.com/google/adk-python
- Google ADK releases: https://github.com/google/adk-python/releases
- Ollama repo: https://github.com/ollama/ollama
- Ollama releases: https://github.com/ollama/ollama/releases

Current Phase 0 finding:

- Google ADK is a runtime candidate for the agent logic layer and is a valid candidate for local evaluation.
- Ollama is a local model runtime candidate and is suitable for development on macOS when run under Docker or local host tooling, but it is not a security boundary.
- Neither runtime layer provides the final authorization boundary or the final Entra validation proof.

## Critical unresolved assumptions

The following assumptions remain unverified:

1. The trusted external authorizer will perform the full Entra JWT validation path required by the repo before requests reach Agent A.
2. The selected agentgateway deployment can enforce A2A and MCP policy boundaries separately when both routes are active.
3. The Entra OBO flow from Agent A to Agent B is valid in the target tenant and app registration model.
4. The final Docker and macOS host routing model is correct for this design.
5. Replay protection is not assumed to be solved by a normal JWT validator alone.

## Evidence required before implementation

- local validation of the proposed external authorizer path against real Entra tokens
- explicit proof of the selected agentgateway gateway policy configuration for A2A and MCP
- sanitized decoded claims and a non-reversible fingerprint of the relevant token or assertion
- successful and failed Entra OBO exchanges from the target tenant
- proof that no raw bearer tokens or reusable credentials are stored in logs or evidence
- local validation that write operations require confirmation, idempotency, and replay protection

This document deliberately does not claim Phase 0 completion.
