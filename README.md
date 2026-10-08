# Local Enterprise Agent POC Starter

Documentation and directory scaffolding for a local, identity-aware, multi-agent banking proof of concept on macOS. This repository intentionally contains **no application code** and no deployable gateway configuration.

## Intended request path

```text
Jupyter Notebook (Mac host)
  -> Kong OSS (Docker API gateway)
  -> Agent A (Google ADK, local; Ollama model)
  -> open-source Agent Gateway (A2A boundary)
  -> Agent B (Google ADK, local)
  -> Agent Gateway (MCP boundary)
  -> local MCP banking mock server (read/write tools)
```

Microsoft Entra ID supplies a test user and separate registrations for Agent A and Agent B. The target design tests user-token validation at the northbound gateway and OAuth 2.0 On-Behalf-Of (OBO) delegation from A toward B.

## Important status and constraints

- This is a planning scaffold, not a working implementation.
- Kong OSS support for the required Entra/OIDC validation is **not assumed**. The team must verify a supported OSS-compatible method or select a documented alternative before implementing protected routes.
- OBO, workload/agent identity, A2A policy enforcement, and MCP authorization are hypotheses to validate, not established capabilities of the selected components.
- “Agent Gateway” is a role in this design until a specific open-source project and release are selected and tested. A product with that phrase in its name is not implicitly endorsed.
- The banking service is a local mock. It must never hold real credentials, accounts, or financial data.
- Macaw is explicitly deferred from this POC.

## Start here

1. Read [docs/architecture.md](docs/architecture.md).
2. Work through the gates in [docs/plan.md](docs/plan.md).
3. Resolve Entra choices in [docs/entra-identity.md](docs/entra-identity.md).
4. Select and verify gateways using [docs/gateway-routing.md](docs/gateway-routing.md).
5. Use [docs/testing.md](docs/testing.md) as the evidence checklist.
6. Give GitHub Copilot the kickoff prompt below, then use the phase prompts in `.github/prompts/` one phase at a time.

## Exact Copilot kickoff prompt

Copy this text exactly into GitHub Copilot Chat from the repository root:

```text
Read README.md, all files under docs/, and .github/copilot-instructions.md before proposing changes. This repository is documentation and scaffolding only right now. First produce a written implementation plan mapped to the phases and acceptance tests in docs/plan.md. Identify every unverified assumption, especially Kong OSS support for Microsoft Entra token validation, the selected open-source Agent Gateway's A2A and MCP capabilities, and Microsoft Entra OBO from Agent A to Agent B. Do not generate application code, Docker configuration, identity secrets, or cloud resources in this step. Do not claim any capability is verified without a cited primary source and local test evidence. Preserve host.docker.internal for container-to-Mac-host traffic. Macaw is out of scope. End with blocking decisions, risks, and the exact evidence required to pass Phase 0.
```

The same prompt is stored in `.github/prompts/plan-project.prompt.md`.

## macOS and Docker networking

Use these conventions consistently during implementation:

- A process running in Docker Desktop reaches a service on the Mac host through `host.docker.internal`, not `localhost`.
- A Mac-host process reaches an exposed container port through `localhost:<published-port>`.
- Containers on the same user-defined Docker network should use their Compose service names.
- Bind host services intentionally. If a service must be reached from Docker, confirm its bind address and firewall exposure; do not casually expose it to the LAN.
- Never place an Entra client secret in a notebook, Git-tracked file, Docker image, or command transcript.

See [docs/gateway-routing.md](docs/gateway-routing.md) for the complete routing matrix.

## Repository map

```text
docs/                         Architecture, identity, routing, plan, and test guidance
.github/copilot-instructions.md
.github/prompts/              Planning prompt plus one prompt per delivery phase
notebooks/                    Future notebook client
infra/kong/                   Future Kong OSS assets
infra/agent-gateway-a2a/      Future A2A gateway assets
infra/agent-gateway-mcp/      Future MCP gateway assets
agents/agent-a/               Future ADK Agent A
agents/agent-b/               Future ADK Agent B
mcp/banking-mock/             Future MCP banking mock server
tests/                        Future contract, identity, integration, and security tests
evidence/                     Future redacted proof collected at each gate
scripts/                      Future local developer helpers
```

Empty directories are retained with `.gitkeep` files. No runtime is implemented yet.

## Definition of a safe POC

The POC is successful only when its evidence shows both allowed and denied paths, correlation across hops, correct delegation semantics, tool-level authorization for reads and writes, and no token or secret leakage. A demo that merely returns a successful banking response is insufficient.

