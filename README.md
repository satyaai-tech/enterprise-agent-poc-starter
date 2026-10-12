# Local Enterprise Agent POC Starter

Documentation, experiment scaffolding, and the active all-Solo roadmap for a local, identity-aware, multi-agent banking proof of concept on macOS. Historical Kong materials are retained as reference evidence, while the active direction is the Solo agentgateway path.

## Active POC direction

The active POC direction is the all-Solo architecture:

```text
Jupyter Notebook (Mac host)
  -> Solo agentgateway API edge
  -> Agent A (Google ADK, local; Ollama model)
  -> Solo agentgateway A2A boundary
  -> Agent B (Google ADK, local; Ollama model)
  -> Solo agentgateway MCP boundary
  -> local MCP banking mock server (read/write tools)
```

Microsoft Entra ID supplies a test user and separate registrations for Agent A and Agent B. The active design tests user-token validation at the northbound API edge, Agent A to Agent B OBO in application code, and independent validation at the Solo agentgateway boundaries before routing and tool execution.

## Important status and constraints

- This repository retains the Kong Phase 0 work as historical/reference evidence only. Kong is not part of the active runtime path for the selected POC direction.
- The all-Solo architecture is the active POC direction and the primary path for ongoing implementation and validation.
- OBO, workload/agent identity, A2A policy enforcement, and MCP authorization remain local POC validations, not production certification.
- “Agent Gateway” is a role in this design until a specific open-source project and release are selected and tested. A product with that phrase in its name is not implicitly endorsed.
- The banking service is a local mock. It must never hold real credentials, accounts, or financial data.
- Macaw is explicitly deferred from this POC.

## Start here

1. Read [docs/architecture.md](docs/architecture.md).
2. Follow the active roadmap in [docs/solo-full-poc-plan.md](docs/solo-full-poc-plan.md).
3. Resolve Entra choices in [docs/entra-identity.md](docs/entra-identity.md).
4. Select and verify gateways using [docs/gateway-routing.md](docs/gateway-routing.md).
5. Use [docs/testing.md](docs/testing.md) as the evidence checklist.
6. Give GitHub Copilot the kickoff prompt below, then use the phase prompts in `.github/prompts/` one phase at a time.

## Active plan and current phase

Use [docs/solo-full-poc-plan.md](docs/solo-full-poc-plan.md) as the active roadmap for the project.

Completed:

- Phase 0: Identity and gateway validation
- Phase 1: Solo API edge
- Phase 2: Solo A2A gateway and Entra OBO
- Phase 3: Solo MCP gateway and banking mock server

Current phase:

- Phase 4: Google ADK agents with local Ollama

Remaining:

- Phase 5: Jupyter end-to-end Solo demonstration

The historical Kong work remains in the repository as reference material only and is not part of the active runtime architecture.

## Exact Copilot kickoff prompt

Copy this text exactly into GitHub Copilot Chat from the repository root:

```text
Read README.md, docs/solo-full-poc-plan.md, docs/architecture.md, docs/testing.md, and .github/copilot-instructions.md before proposing changes. Treat the all-Solo architecture as the active POC path. Follow the active roadmap in docs/solo-full-poc-plan.md and focus on the next phase: Phase 3, the Solo MCP gateway and banking mock server. Preserve the historical Kong material as reference only; do not restart Phase 0 or re-open the Kong investigation as an active task. Keep the security and evidence guardrails in place: no real credentials, no raw tokens, no personal identity claims, no live Entra calls or live docker execution during planning, and no unsupported production claims. Do not generate implementation code for phases outside the selected task. End with the assumptions, decisions, files to change, evidence needed for the next gate, and any remaining risks.
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
infra/kong/                   Historical Kong reference assets
infra/agent-gateway-a2a/      Future A2A gateway assets
infra/agent-gateway-mcp/      Future MCP gateway assets
agents/agent-a/               Future ADK Agent A
agents/agent-b/               Future ADK Agent B
mcp/banking-mock/             Future MCP banking mock server
tests/                        Future contract, identity, integration, and security tests
evidence/                     Future redacted proof collected at each gate
scripts/                      Future local developer helpers
```

The repository retains historical reference material for the earlier Kong path and the active Solo implementation plan for the current POC direction.

## Definition of a safe POC

The POC is successful only when its evidence shows both allowed and denied paths, correlation across hops, correct delegation semantics, tool-level authorization for reads and writes, and no token or secret leakage. A demo that merely returns a successful banking response is insufficient.

