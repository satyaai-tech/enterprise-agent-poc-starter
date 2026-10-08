# Phase 0 evidence directory

This directory holds Phase 0 verification artifacts for the local repository only.

## Current status

Status: PENDING

The repository is intentionally not marking Phase 0 complete. The live Entra tenant-backed path is intentionally withheld until the operator populates a private `.env` locally and runs the live spike from a local VS Code terminal.

## Safe usage

```bash
cd /Users/satyaanumolu/POCs/enterprise-agent-poc-starter
uv sync
uv run pytest tests/identity -q
cp .env.example .env
chmod 600 .env
uv run python tests/identity/entra_device_obo_spike.py --live
```

Do not store raw tokens, secrets, usernames, emails, OIDs, or personal claims in source-controlled files.
