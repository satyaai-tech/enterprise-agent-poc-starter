---
mode: agent
description: Implement and verify the local runtime and networking skeleton
---

> Legacy notice: this prompt reflects the original numbered Phase 1 sequence and is retained for historical reference. The active roadmap is [docs/solo-full-poc-plan.md](../../docs/solo-full-poc-plan.md). This file should not be used as the current implementation path.

Implement only Phase 1 after Phase 0 evidence is approved. Before editing, summarize the selected pinned components, ports, trust boundaries, and files to change. Use host.docker.internal for container-to-Mac-host calls, localhost with published ports for Mac-to-container calls, and service names for container-to-container calls. Add no agent business behavior. Commit no secrets. Add health, connectivity, clean-start, and secret-scan checks; capture redacted evidence for every Phase 1 acceptance test. Stop if a Phase 0 decision is missing or a proposed change would expose an undocumented bypass.

