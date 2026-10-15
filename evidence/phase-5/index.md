# Phase 5 Evidence Index

## Current status

- Phase 5 status: COMPLETE
- Slice 5A status: COMPLETE (read-only evidence only)
- Slice 5B status: COMPLETE
- Slice 5C status: COMPLETE — Per-User Read/Write Authorization (live two-user evidence below)
- Slice 5D status: NEXT / PLANNED — OpenTelemetry and Arize Phoenix telemetry; not implemented or verified
- Phase 6 status: PLANNED — FastMCP-compatible Banking MCP conversion and MACAW policy enforcement

## Notes

- Do not treat the existing Slice 5A read-only evidence as write-capable or as proof of controlled transfers.
- Slice 5C used two independent Entra POC test identities, `poc-banking-reader` and `poc-banking-writer`, and passed guarded live validation; its evidence is listed below.
- MACAW and FastMCP remain separate planned Phase 6 work and are not part of this slice.

## Artifacts

- [slice-5c-two-user-authorization-20261015T015546Z.json](slice-5c-two-user-authorization-20261015T015546Z.json)
  - Guarded live Reader/Writer run: PASS. Exactly one authorized transfer mutation (replay and denied requests added none)
  - Reader: Banking.Read scope, Banking.Reader role, no Banking.Writer role; only `get_account_summary` discoverable; transfer denied
  - Writer: Banking.Read and Banking.Write scopes, Banking.Reader and Banking.Writer roles; both tools discoverable
  - Sanitized: pseudonymous identity references only; synthetic 92 and regression 23 tests passed

- [slice-5a-read-only-e2e-20261013T012701Z.json](slice-5a-read-only-e2e-20261013T012701Z.json)
  - Three consecutive successful runs of:
    - `uv run pytest tests/integration/test_solo_agentgateway_unified.py::test_unified_slice_5a_read_only_end_to_end -q -s`
  - No repository edits during the gate (matching pre/post git-status hashes)
  - Read-only counters confirmed at zero for each successful run
  - No leftover `solo-slice-5a-*` containers after execution
