# Copilot Instructions

## Repository purpose

This repository begins as documentation and empty scaffolding for a local enterprise-agent POC. Follow `docs/plan.md` phase by phase. Do not skip acceptance gates.

## Non-negotiable rules

- Never claim an integration works without a pinned version, primary-source support, and local evidence.
- Treat Kong OSS validation of Microsoft Entra tokens as unverified until Phase 0 proves the exact mechanism. Do not assume enterprise OIDC plugins exist in OSS.
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

There is no application code or deployable configuration. When using the planning prompt, produce a plan only. Do not create implementation files until the user explicitly selects a phase and asks for implementation.

