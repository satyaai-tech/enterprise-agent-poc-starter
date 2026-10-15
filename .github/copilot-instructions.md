# Copilot Instructions

## Repository purpose

This repository is a local enterprise-agent POC centered on the all-Solo architecture. Follow the active plan in [docs/solo-full-poc-plan.md](../docs/solo-full-poc-plan.md). Preserve the historical Kong material as reference only and do not skip the evidence gates for the active Solo roadmap.

## Active plan and phase sequence

- Active plan: [docs/solo-full-poc-plan.md](../docs/solo-full-poc-plan.md)
- Active gateway: Solo agentgateway as the primary POC gateway
- Historical/reference work: Kong and prior Phase 0 materials remain preserved for comparison only
- Active remaining sequence:
  1. Phase 3: Solo MCP gateway and banking mock server
  2. Phase 4: Google ADK agents with local Ollama
  3. Phase 5: Jupyter end-to-end Solo demonstration (COMPLETE)
  4. Phase 6: PLANNED — MACAW policy enforcement and FastMCP-compatible Banking MCP conversion

## Slice 5 status

- Slice 5A: COMPLETE — documented and supported by existing read-only evidence
- Slice 5B: COMPLETE
- Slice 5C: COMPLETE — Per-User Read/Write Authorization (evidence in `evidence/phase-5/`)
- Slice 5D: NEXT / PLANNED — OpenTelemetry and Arize Phoenix telemetry; not implemented

Phase 5 is COMPLETE. Do not claim telemetry, MACAW, FastMCP or production readiness without new evidence.

## Non-negotiable rules

- Never claim an integration works without a pinned version, primary-source support, and local evidence.
- Treat Kong OSS validation of Microsoft Entra tokens as historical/reference material unless a specific active Solo decision reopens it; do not reframe earlier Kong work as the active implementation path.
- Treat “Agent Gateway” as an architectural role until a specific open-source project and version pass the capability matrix.
- Do not invent an “agent identity blueprint.” Use documented OAuth/OIDC behavior and label design choices as POC-specific.
- Do not equate forwarding Agent A's access token with Entra OBO. B must receive and validate a token intended for B.
- Authorization belongs in gateways and services, never in model prompts or model output.
- Separate MCP read and write permissions. Writes require explicit authorization, confirmation semantics, idempotency, replay protection, and audit evidence.
- Use fake data only. Never add real banking data, credentials, tenant secrets, client secrets, tokens, or decoded reusable JWTs.
- Do not add Macaw; it is deferred.

## Networking rules

- Container to Mac host: `host.docker.internal:<port>` on Docker Desktop for Mac.
- Mac host to published container: `localhost:<published-port>`.
- Container to container: Compose service name on a user-defined network.
- Never use a container's `localhost` to represent the Mac host.
- Minimize published ports and document all bind addresses and bypass risks.

## Work style

- Before a phase, state assumptions, decisions, files to change, tests, and rollback.
- Keep changes within the active phase.
- Prefer version-pinned, documented dependencies and maintained security libraries.
- Add tests with implementation, including negative cases.
- Fail closed on identity, metadata, gateway, or policy failure.
- Redact logs and propagate an opaque correlation ID.
- Update documentation and the relevant `evidence/phase-N/` index after verification.
- Clearly label illustrative names, ports, scopes, and schemas until approved.

## Current state

The active repository path is the all-Solo architecture. When using the planning prompt, produce a plan only for the selected active phase and keep historical Kong material clearly marked as reference work. Do not create implementation files outside the selected phase and do not claim production readiness without local evidence.

