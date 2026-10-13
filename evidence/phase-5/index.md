# Phase 5 Evidence Index

## Current status

- Phase 5 status: IN PROGRESS
- Slice 5A status: COMPLETE (read-only evidence only)
- Slice 5B status: PLANNED / guarded live validation required before completion can be claimed
- Slice 5C status: PLANNED / NOT STARTED — Per-User Read/Write Authorization
- Phase 6 status: PLANNED — FastMCP-compatible Banking MCP conversion and MACAW policy enforcement

## Notes

- Do not treat the existing Slice 5A read-only evidence as write-capable or as proof of controlled transfers.
- Slice 5C requires two independent Entra POC test identities, `poc-banking-reader` and `poc-banking-writer`, plus guarded live validation before Phase 5 may be marked complete.
- MACAW and FastMCP remain separate planned Phase 6 work and are not part of this slice.

## Artifacts

- [slice-5a-read-only-e2e-20261013T012701Z.json](slice-5a-read-only-e2e-20261013T012701Z.json)
  - Three consecutive successful runs of:
    - `uv run pytest tests/integration/test_solo_agentgateway_unified.py::test_unified_slice_5a_read_only_end_to_end -q -s`
  - No repository edits during the gate (matching pre/post git-status hashes)
  - Read-only counters confirmed at zero for each successful run
  - No leftover `solo-slice-5a-*` containers after execution
