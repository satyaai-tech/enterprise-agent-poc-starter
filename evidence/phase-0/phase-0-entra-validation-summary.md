# Phase 0: Microsoft Entra identity validation spike

## Status

Status: PENDING

The live Entra/OBO execution recorded in `evidence/phase-0/phase-0-entra-validation-results.json` remains the repository's historical local validation evidence. That JSON is immutable and records that the live Agent A and Agent B tokens passed signature, issuer, tenant, audience, lifetime, and scope checks on 2026-10-08.

The authorized-client validation (`azp` for v2 and `appid` for v1) is newly implemented in the synthetic identity harness, but it remains pending live tenant verification. Phase 0 overall remains PENDING, and the Kong/external-authorizer integration remains unverified.

## Scope

This repository contains the Phase 0 identity validation scaffold and synthetic-only unit tests. The live device-code and OBO flow is implemented as a guarded code path but is intentionally not executed by default.

## Safe evidence rules

- No raw tokens are stored in source-controlled files.
- No client secrets, usernames, emails, or personal claims are stored.
- Only redacted or fingerprinted evidence may be kept in this directory.
- Real tenant-backed validation remains pending operator execution in a private local environment.

## Manual execution

After copying `.env.example` to `.env` privately and filling in exact portal values, run:

```bash
cd /Users/satyaanumolu/POCs/enterprise-agent-poc-starter
uv sync
uv run python tests/identity/entra_device_obo_spike.py --live
```

This is not marked as a success result in the repository.
