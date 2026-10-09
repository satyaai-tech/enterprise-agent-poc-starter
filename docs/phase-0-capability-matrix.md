# A2A and MCP capability matrix (Phase 0 COMPLETE)

This matrix intentionally distinguishes between what is documented in official sources and what the project has actually verified locally. Documentation alone is never assigned `Locally Verified` status. Phase 0 is complete; A2A/MCP deployment verification and banking write controls are later-phase work.

## Status legend

- `Documented`: officially described by the project or protocol sources
- `Not Sufficient By Itself`: functionally present but inadequate for the full required security/validation behavior
- `Locally Verified`: proven in the local environment with test evidence
- `Absent`: explicitly not provided or not available in the official upstream project
- `Unknown`: not yet evidenced locally and not proven by the available documentation
- `Locally Unverified`: documented or configured as a candidate but not yet validated in the local environment

## Gateway and protocol candidate evaluation

| Capability | Candidate | Status | Evidence basis |
|---|---|---|---|
| A2A protocol exists and is versioned | A2A project | Documented | A2A official releases show `v1.0.1` and the project is active. |
| MCP protocol exists and is versioned | MCP specification | Documented | MCP official release `2026-07-28` is published and the architecture docs explain the protocol. |
| A2A gateway product is a first-class upstream offering | agentgateway/agentgateway | Documented | The official README explicitly lists an `A2A Gateway` role and its features. |
| Proposed A2A gateway boundary deployment | agentgateway v1.6.0 (A2A) | Locally Unverified | Candidate deployment selected for evaluation in Phase 3, not a Phase 0 blocker. |
| MCP gateway product is a first-class upstream offering | agentgateway/agentgateway | Documented | The official README explicitly lists an `MCP Gateway` role and its features. |
| Proposed MCP gateway boundary deployment | agentgateway v1.6.0 (MCP) | Locally Unverified | Candidate deployment selected for evaluation in Phase 4, not a Phase 0 blocker. |
| Kong OpenID Connect plugin is available in Kong OSS | Kong OSS | Absent | The official Kong OpenID Connect docs page metadata marks the plugin as `enterprise`; it is not a Kong OSS solution. |
| Kong OSS JWT plugin provides complete Entra validation | Kong OSS JWT | Not Sufficient By Itself | The generic JWT plugin is not an OIDC discovery, JWKS, or Entra tenant broker and is not enough for the full required Entra validation. |
| Kong OSS JWT plugin supports automatic JWKS/key rotation for Entra | Kong OSS JWT | Absent | The bundled plugin itself does not supply this behavior; a separate external component must provide it. |
| Exact Entra issuer validation is implemented | Proposed external authorizer | Locally Verified | Proven by the live and synthetic validation artifacts. |
| Exact Entra audience validation is implemented | Proposed external authorizer | Locally Verified | Proven by the live and synthetic validation artifacts. |
| Exact Entra tenant validation is implemented | Proposed external authorizer | Locally Verified | Proven by the live and synthetic validation artifacts. |
| Exact Entra delegated-scope enforcement is implemented | Proposed external authorizer | Locally Verified | Proven by the live and synthetic validation artifacts. |
| Exact Entra authorized-client enforcement is implemented | Proposed external authorizer | Locally Verified | Proven by `phase-0-entra-authorized-client-validation-20261009T004249732177Z.json`. |
| A2A/MCP gateway auth hooks are explicitly configured | agentgateway/agentgateway | Documented | Official README lists `Auth (JWT, API keys, OAuth)` and RBAC policy. |
| Gateway-level authorization policy engine is documented | agentgateway/agentgateway | Documented | Official README documents a CEL policy engine. |
| Observability is documented | agentgateway/agentgateway | Documented | Official README documents OpenTelemetry metrics/logs/tracing. |
| Replay protection is built into a normal JWT validator | Generic JWT validation | Absent | A generic JWT validator checks signature, expiry, and claims; it does not by itself provide replay detection or sender-constrained message protection. |
| Local Docker/macOS deployment path is proven for this repo | Kong OSS + external authorizer | Locally Verified | Proven by the Docker-backed Kong -> proxy -> mock Agent A integration test. |
| Locally verified Entra OBO success/failure path | Entra OBO flow | Locally Verified | Proven by the live `phase-0-entra-validation-results.json` artifact. |
| Locally verified A2A/MCP gateway policy boundary separation | Selected gateway | Deferred to Phase 3/4 | Not part of Phase 0; to be proven in later phases. |
| Locally verified write confirmation and idempotency enforcement | control plane + banking mock | Deferred to Phase 4 | Not part of Phase 0; to be proven in later phases. |

## Interpretation

- `Documented` status means the feature is described in the official project or protocol sources.
- `Absent` means the official project does not present that capability as part of the OSS path or as a universal guarantee.
- `Unknown` means the system has not yet passed the local tenant/Docker evidence gate required by its phase.
- `Deferred to Phase 3/4` means the capability is intentionally out of Phase 0 scope.
- `Locally Verified` is intentionally reserved for evidence collected after the actual environment and tenant validation has been completed.

## Decision status

The project should not treat any later-phase capability as `Locally Verified` until that phase's validation has completed. Phase 0 is complete.
