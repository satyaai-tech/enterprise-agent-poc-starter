from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


def build_evidence_destination(root: Path, *, prefix: str = "phase-0-entra-authorized-client-validation") -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    suffix = uuid4().hex[:8]
    return root / f"{prefix}-{timestamp}-{suffix}.json"


def write_evidence(result: dict[str, Any], *, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(result, indent=2, sort_keys=True) + "\n")