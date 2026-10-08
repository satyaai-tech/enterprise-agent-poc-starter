# Phased Implementation Plan and Acceptance Tests

No phase may be called complete without the listed evidence. Phase prompts under `.github/prompts/` guide Copilot; they do not override these gates.

## Phase 0 — Decisions, source verification, and threat model

### Work

- Record pinned versions for Kong OSS, Google ADK, Ollama, the A2A protocol/specification, MCP, and each proposed gateway.
- Verify from primary documentation and a minimal local spike whether Kong OSS can validate the exact Entra-issued JWTs required here.
- If it cannot, document and choose an alternative such as validation in a small trusted auth service, a verified community plugin with an explicit risk decision, or a different gateway/edition. Do not silently substitute one.
- Select specific open-source gateway project(s) for the A2A and MCP roles. Verify license, maintenance state, version, supported protocols, authentication hooks, policy controls, and Docker/macOS compatibility.
- Verify the Entra OBO topology: audiences, scopes, consent, client type, credential needs, and which hop performs token exchange.
- Threat-model token theft, confused deputy, prompt injection, tool abuse, replay, excessive write scope, cross-user access, and log leakage.
- Confirm that Macaw remains out of scope.

### Acceptance tests

- A decision record identifies each selected component and exact version.
- Primary-source links and a reproducible local test show the actual Kong token-validation outcome; no marketing inference counts.
- A signed-off fallback exists if Kong OSS cannot meet the requirement.
- Captured Entra token claims (redacted) prove intended `iss`, `aud`, `tid`, `scp`/`roles`, `azp`/`appid`, and lifetime values.
- A gateway capability matrix labels every required A2A/MCP feature as verified, absent, or unknown.
- A data-flow diagram and threat register identify all trust boundaries and mitigations.

## Phase 1 — Local runtime and network skeleton

### Work

- Establish Docker Compose boundaries and a user-defined network.
- Reserve documented ports and health endpoints.
- Establish host/container addressing with `host.docker.internal` for container-to-Mac calls.
- Create deterministic environment-variable names and local secret-injection procedures without committing values.
- Stand up placeholder health paths before agent behavior.

### Acceptance tests

- Every host-to-container, container-to-host, and container-to-container path in the routing matrix has a connectivity check.
- No service depends on container `localhost` to reach the Mac host.
- Startup from a clean machine follows one documented sequence.
- Repository and image scans find no secrets or tokens.
- All service versions and health results are captured under `evidence/phase-1/`.

## Phase 2 — Northbound user identity and Agent A

### Work

- Configure the test client and Agent A registration according to the approved identity design.
- Implement token acquisition outside source-controlled notebook cells.
- Configure the verified edge-validation approach and route to Agent A.
- Connect Agent A to local Ollama; keep authorization outside the model.

### Acceptance tests

- A valid test-user token with the exact expected audience and scope reaches Agent A.
- Missing, expired, wrong-issuer, wrong-tenant, wrong-audience, malformed, and wrong-scope tokens are denied.
- Agent A cannot be reached through an unintended bypass route.
- A prompt cannot override gateway or server-side authorization.
- Logs correlate the request without exposing the bearer token.

## Phase 3 — A-to-B delegation through the A2A boundary

### Work

- Configure Agent B's protected API and delegated scope.
- Implement the verified OBO exchange at the approved middle-tier component.
- Introduce the selected A2A gateway and its version-pinned contract.
- Validate the downstream token again at Agent B.

### Acceptance tests

- A permitted user request results in a B-audience token and a successful authorized Agent B call.
- Passing the A-audience token directly to B fails.
- App-only, wrong-user, wrong-scope, expired, replayed, and tampered requests fail as designed.
- Consent or conditional-access failures are observable and do not fall back to a broader identity.
- The A2A gateway blocks an unregistered target, disallowed operation, oversized payload, and unauthenticated caller.
- Evidence distinguishes what is enforced by Entra, the gateway, Agent A, and Agent B.

## Phase 4 — MCP banking mock with read/write policy

### Work

- Define minimal fake banking resources and deterministic read/write behavior.
- Define MCP tool schemas, separating read operations from state-changing operations.
- Introduce the verified MCP gateway and explicit per-tool policy.
- Require idempotency and an explicit confirmation design for writes.

### Acceptance tests

- An authorized read returns only the test user's fake account data.
- Cross-user reads, unknown tools, malformed arguments, and overbroad queries are denied.
- A write without required scope, confirmation, or idempotency key is denied.
- A valid write occurs exactly once; replay does not duplicate it.
- Tool output is treated as untrusted data and cannot inject instructions that bypass policy.
- The mock contains no real personal, financial, or credential data.

## Phase 5 — End-to-end hardening and demo

### Work

- Run the full notebook → Kong → A → A2A gateway → B → MCP gateway → mock path.
- Add negative, resilience, concurrency, latency, and restart tests.
- Verify redaction, least privilege, dependency provenance, and reproducibility.
- Prepare a demo script that includes denied paths and known limitations.

### Acceptance tests

- A complete read and a complete controlled write pass end to end with one correlation ID.
- The negative test matrix in `docs/testing.md` passes.
- A gateway or agent outage fails closed; it does not bypass policy or silently change identity.
- Restart/replay cannot repeat a completed write.
- A fresh setup using only approved documentation reproduces the result.
- The final report lists remaining unknowns and never upgrades a POC finding into a production claim.

## Exit criteria

The POC is complete when Phases 0–5 have redacted evidence, all security-critical negative tests pass, and unresolved limitations are documented. It is not complete merely because the happy path runs.

