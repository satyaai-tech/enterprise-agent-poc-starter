from __future__ import annotations

import os
from pathlib import Path


class FileTokenProvider:
    """Read a single opaque bearer token from a file configured at runtime."""

    def __init__(self, token_path: str | os.PathLike[str]):
        self.token_path = Path(token_path)
        self._token: str | None = None
        self._validate_token_file()

    @classmethod
    def from_env(cls, env_var: str) -> "FileTokenProvider":
        token_file = os.environ.get(env_var)
        if not token_file:
            raise RuntimeError(f"Missing required environment variable: {env_var}")
        return cls(token_file)

    def _validate_token_file(self) -> None:
        try:
            if not self.token_path.exists():
                raise FileNotFoundError(self.token_path)
            raw = self.token_path.read_text(encoding="utf-8")
        except OSError as exc:  # pragma: no cover - narrow failure path
            raise RuntimeError(f"Token file unreadable: {self.token_path}") from exc
        token = raw.strip()
        if not token:
            raise RuntimeError(f"Token file empty: {self.token_path}")
        self._token = token

    @property
    def token(self) -> str:
        if self._token is None:
            self._validate_token_file()
        return self._token or ""

    def get_token(self) -> str:
        return self.token


__all__ = ["FileTokenProvider"]
