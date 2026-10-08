---
mode: agent
description: Implement northbound identity enforcement and Agent A
---

Implement only Phase 2 after Phases 0 and 1 pass. Use the explicitly approved Kong OSS token-validation mechanism or documented alternative; never assume OIDC support. Implement token acquisition without storing secrets or tokens in the notebook. Keep authorization outside the model. Connect Agent A to local Ollama only for reasoning. Add all positive and negative edge-token tests from docs/plan.md and docs/testing.md, bypass tests, and redacted correlation evidence. Stop rather than weakening issuer, audience, tenant, signature, lifetime, client, or scope checks.

