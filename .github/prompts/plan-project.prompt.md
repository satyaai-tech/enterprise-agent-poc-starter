---
mode: agent
description: Plan the enterprise agent POC without writing implementation code
---

Read README.md, all files under docs/, and .github/copilot-instructions.md before proposing changes. This repository is documentation and scaffolding only right now. First produce a written implementation plan mapped to the phases and acceptance tests in docs/plan.md. Identify every unverified assumption, especially Kong OSS support for Microsoft Entra token validation, the selected open-source Agent Gateway's A2A and MCP capabilities, and Microsoft Entra OBO from Agent A to Agent B. Do not generate application code, Docker configuration, identity secrets, or cloud resources in this step. Do not claim any capability is verified without a cited primary source and local test evidence. Preserve host.docker.internal for container-to-Mac-host traffic. Macaw is out of scope. End with blocking decisions, risks, and the exact evidence required to pass Phase 0.

