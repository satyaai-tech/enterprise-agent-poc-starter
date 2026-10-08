---
mode: agent
description: Implement the MCP boundary and fake banking read/write tools
---

Implement only Phase 4 after prior phases pass. Use only fake banking data. Use the selected, pinned, and verified MCP gateway and protocol version. Define narrow schemas and separate read from write policy. Bind authorization to trusted user and caller context; never to natural-language claims. Require confirmation and idempotency for writes, block replay, and audit decisions without logging tokens or sensitive payloads. Add cross-user, unknown-tool, malformed-input, prompt-injection, missing-scope, missing-confirmation, replay, and gateway-outage tests. Capture evidence against every Phase 4 acceptance test.

