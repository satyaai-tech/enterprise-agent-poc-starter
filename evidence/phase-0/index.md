# Phase 0 evidence index (PENDING)

## Status

Status: PENDING

This index tracks the evidence required to move the repository beyond the documentation-only Phase 0 state. No item here is marked Verified yet.

## Version source check (candidate versions only)

The following candidate versions were checked directly against the official project release sources on 2026-10-08.

| Project | Official source | Release tag | Release date (UTC) | Date checked |
|---|---|---|---|---|
| Kong Gateway OSS | https://github.com/Kong/kong/releases | 3.9.3 | 2026-06-17T06:02:19Z | 2026-10-08 |
| Google ADK | https://github.com/google/adk-python/releases | v2.11.0 | 2026-10-02T00:44:26Z | 2026-10-08 |
| Ollama | https://github.com/ollama/ollama/releases | v0.40.1 | 2026-10-07T23:22:59Z | 2026-10-08 |
| A2A | https://github.com/a2aproject/A2A/releases | v1.0.1 | 2026-05-28T11:34:36Z | 2026-10-08 |
| MCP spec | https://github.com/modelcontextprotocol/modelcontextprotocol/releases | 2026-07-28 | 2026-07-28T16:47:49Z | 2026-10-08 |
| agentgateway | https://github.com/agentgateway/agentgateway/releases | v1.6.0 | 2026-10-02T16:26:26Z | 2026-10-08 |

## Required evidence set

| Evidence item | Required content | Status |
|---|---|---|
| Component version pinning | Official candidate versions recorded and source-checked; no deployment pin yet | PENDING |
| Northbound routing gateway selection | Kong Gateway OSS 3.9.3 selected as the required northbound routing gateway | PENDING |
| External Entra validation design | Trusted external authorizer selected as the proposed complete Entra JWT validation design before Agent A | PENDING |
| OBO proof | Real OBO exchange, audience checks, delegated-scope checks, and failure cases | PENDING |
| A2A gateway candidate | agentgateway v1.6.0 selected as the evaluation candidate for a separate A2A gateway boundary | PENDING |
| MCP gateway candidate | agentgateway v1.6.0 selected as the evaluation candidate for a separate MCP gateway boundary | PENDING |
| Threat model approval | Trust boundaries, fail-closed behavior, and replay-control plan | PENDING |
| Local Docker and host routing proof | host.docker.internal and localhost rules validated under Docker Desktop/macOS | PENDING |
| Negative tests | Wrong audience, wrong tenant, wrong scope, expired tokens, malformed JWTs, direct forwarding of A token to B | PENDING |
| Audit evidence | Redacted claims, non-reversible fingerprinting, correlation IDs, and trace IDs only | PENDING |

## Source material captured for decision making

- Kong GitHub releases: https://github.com/Kong/kong/releases
- Kong JWT plugin: https://developer.konghq.com/plugins/jwt/
- Kong OpenID Connect plugin: https://developer.konghq.com/plugins/openid-connect/
- Google ADK releases: https://github.com/google/adk-python/releases
- Ollama releases: https://github.com/ollama/ollama/releases
- A2A releases: https://github.com/a2aproject/A2A/releases
- MCP releases: https://github.com/modelcontextprotocol/modelcontextprotocol/releases
- MCP architecture docs: https://modelcontextprotocol.io/docs/2026-07-28/learn/architecture
- Microsoft Entra OBO flow: https://learn.microsoft.com/entra/identity-platform/v2-oauth2-on-behalf-of-flow
- Microsoft Entra token validation docs: https://learn.microsoft.com/entra/identity-platform/access-tokens
- agentgateway repo: https://github.com/agentgateway/agentgateway
- agentgateway releases: https://github.com/agentgateway/agentgateway/releases

## Evidence rules for token artifacts

- Do not store an exact OBO assertion, access token, refresh token, client secret, or reusable credential in the repo.
- Evidence may contain sanitized decoded claims and a non-reversible fingerprint only.
- Token evidence must be redacted and must not be recoverable from the stored artifact.

## Minimum operator checklist for the next validation step

The following inputs are required before the next validation pass can run:

1. Tenant ID for the test Entra directory
2. Real client IDs for the Agent A and Agent B app registrations
3. Real Application ID URIs and delegated scopes for the downstream B API
4. Whether the middle tier uses a secret or certificate for the OBO token exchange
5. A test user account that is safe for local validation and not production data
6. Docker Desktop environment on macOS with local access to the host network
7. A known-good route for the macOS host to the container and container-to-host connectivity
8. The exact versions to deploy for Kong, ADK, and the selected gateway/runtime candidates

## Required local test matrix

### Identity tests

- valid A token -> validated
- valid OBO exchange -> valid B token issued
- wrong audience -> rejected
- wrong scope -> rejected
- expired token -> rejected
- missing `iss` or `tid` -> rejected
- wrong tenant -> rejected
- direct forwarding of A token to B -> rejected

### Gateway and route tests

- container to host uses host.docker.internal when the target is on the macOS host
- container to container uses the Compose service name
- Mac host to published container uses localhost:published-port
- no accidental binding to 0.0.0.0 unless justified and documented

### Write protection tests

- confirmation required for write operations
- idempotency key used when the action is retried
- explicit replay detection or duplicate suppression in place
- all write attempts logged with a correlation ID only

## Synthetic validation artifact added for this repo

The repository now includes a synthetic-only identity validation harness under `tests/identity/` and a pending evidence folder under `evidence/phase-0/`.

- `tests/identity/entra_device_obo_spike.py` implements the live device-code and OBO flow as a guarded code path behind `--live`.
- `tests/identity/test_entra_identity_validation.py` validates synthetic tokens and negative cases without contacting Entra.
- The live tenant-backed flow remains Pending and is not executed by default.
- The system does not store raw tokens, the Agent A client secret, personal claims, or complete authentication errors in source-controlled files.

## Stop condition

Phase 0 may move to implementation only after the evidence set above is collected and the project owner approves the exact Entra validation and gateway design.

This file is intentionally not a completion certificate.
