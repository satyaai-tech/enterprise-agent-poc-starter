---
mode: agent
description: Plan the next active Solo Phase 3: MCP gateway and banking mock server
---

This is a planning prompt only.

Read [docs/solo-full-poc-plan.md](../../docs/solo-full-poc-plan.md), [docs/architecture.md](../../docs/architecture.md), [docs/gateway-routing.md](../../docs/gateway-routing.md), [docs/testing.md](../../docs/testing.md), and [.github/copilot-instructions.md](../copilot-instructions.md) before proposing changes. Treat the all-Solo architecture as the active POC path and treat the historical Kong material as reference only. Do not restart Phase 0 or reopen the Kong investigation as an active task.

Focus on Phase 3: the Solo MCP gateway and the banking mock server. Keep the work scoped to a written implementation plan only. Do not generate implementation code, Docker configuration, infrastructure files, secrets, cloud resources, live Entra access, or terminal commands. Do not claim production readiness. Identify assumptions, files to change, security controls, test plan, evidence requirements, and rollback or failure behavior. Preserve the security and evidence guardrails already established for the repo: no real banking data, no raw tokens, no personal identity claims, no live token calls, and no unsupported capability claims.

End with:

- the exact plan for the Phase 3 MCP boundary and banking mock work
- the acceptance tests required for the next gate
- the evidence artifacts to capture
- blockers, risks, and any unresolved assumptions
