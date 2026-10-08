# Entra identity validation spike

This directory contains the Phase 0 identity validation harness and synthetic tests only.

## Scope

- The live Entra device-code and OBO path is implemented as a guarded code path, but not executed in this repository by default.
- Unit tests use synthetic tokens and mocks only. They never contact Microsoft Entra.
- The live path must be run manually from a local VS Code terminal after the operator has populated `.env` privately.

## Safe commands

```bash
cd /Users/satyaanumolu/POCs/enterprise-agent-poc-starter
uv sync
uv run pytest tests/identity -q
cp .env.example .env
chmod 600 .env
uv run python tests/identity/entra_device_obo_spike.py --live
```

## Required local setup

1. Copy `.env.example` to `.env` in your private local environment.
2. Fill in the exact values from your Entra portal.
3. Restrict file permissions to owner-read/write only.
4. Run the live spike only from your local terminal with the `--live` flag.

Do not commit `.env` or any tokens to source control.
