#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
SPIKE_DIR = Path(__file__).resolve().parent
EVIDENCE_DIR = REPO_ROOT / "evidence" / "solo-phase-2"


def load_root_env() -> dict[str, str]:
    env_path = REPO_ROOT / ".env"
    values: dict[str, str] = {}
    if not env_path.exists():
        return values
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def ensure_evidence_dir() -> None:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)


def sanitize_for_evidence(value: Any) -> Any:
    if isinstance(value, str):
        return value[:32] + ("..." if len(value) > 32 else "")
    if isinstance(value, dict):
        return {str(k): sanitize_for_evidence(v) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize_for_evidence(item) for item in value]
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Live Solo A2A/OBO validation runner")
    parser.add_argument("--live", action="store_true", help="Required to execute the live device-code and OBO flow")
    args = parser.parse_args()
    if not args.live:
        raise SystemExit("Refusing to run. Re-run with --live to execute the live device-code and OBO flow.")

    env = os.environ.copy()
    env.update(load_root_env())
    ensure_evidence_dir()

    # This file intentionally avoids executing the live flow in this workspace.
    # The real implementation should reuse the existing Phase 0 device-code and OBO flow,
    # fetch Token A, exchange it for Token B, send Token B through the A2A gateway,
    # keep tokens in memory only, and write sanitized evidence under evidence/solo-phase-2.
    print("Live execution is intentionally disabled in this workspace. Use the existing Phase 0 device-code/OBO implementation and pass --live only when you explicitly want to run the live exchange.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
