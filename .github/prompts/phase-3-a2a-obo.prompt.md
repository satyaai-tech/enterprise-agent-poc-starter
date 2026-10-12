---
mode: agent
description: Implement Entra OBO and the A-to-B boundary
---

> Legacy notice: this prompt reflects the original numbered phase sequence and is retained for historical reference. The active roadmap is [docs/solo-full-poc-plan.md](../../docs/solo-full-poc-plan.md). Solo Phase 2 is complete; the active next phase is Solo Phase 3 for the MCP boundary and banking mock server.

Implement only Phase 3 after earlier acceptance tests pass. Use the selected and version-pinned A2A gateway whose required capabilities were verified in Phase 0. Implement true Microsoft Entra OBO according to the approved registration design; do not forward the Agent A token to Agent B and do not fall back to client credentials. Agent B must validate its own audience, issuer, tenant, lifetime, authorized caller, and delegated scope. Add failure tests for consent, claims challenges, wrong audience/scope/user, app-only tokens, replay, malformed A2A messages, unknown targets, and gateway outage. Capture redacted evidence showing which component enforces each decision.

