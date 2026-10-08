---
mode: agent
description: Implement Entra OBO and the A-to-B boundary
---

Implement only Phase 3 after earlier acceptance tests pass. Use the selected and version-pinned A2A gateway whose required capabilities were verified in Phase 0. Implement true Microsoft Entra OBO according to the approved registration design; do not forward the Agent A token to Agent B and do not fall back to client credentials. Agent B must validate its own audience, issuer, tenant, lifetime, authorized caller, and delegated scope. Add failure tests for consent, claims challenges, wrong audience/scope/user, app-only tokens, replay, malformed A2A messages, unknown targets, and gateway outage. Capture redacted evidence showing which component enforces each decision.

