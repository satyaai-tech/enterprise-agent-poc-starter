from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

REQUIRED_OLLAMA_MODEL = "qwen3:8b"
REQUIRED_OLLAMA_API_BASE = "http://localhost:11434"
ALLOWED_OLLAMA_API_BASES = {"http://localhost:11434", "http://host.docker.internal:11434"}


@dataclass(frozen=True)
class LocalOllamaConfig:
    ollama_model: str
    ollama_api_base: str

    @property
    def model_name(self) -> str:
        return f"ollama_chat/{self.ollama_model}"

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
        *,
        context: str | None = None,
    ) -> "LocalOllamaConfig":
        values = os.environ if env is None else env
        model = values.get("OLLAMA_MODEL", "").strip()
        api_base = values.get("OLLAMA_API_BASE", "").strip()

        missing = []
        if not model:
            missing.append("OLLAMA_MODEL")
        if not api_base:
            missing.append("OLLAMA_API_BASE")
        if missing:
            message = "Missing local Ollama configuration: " + ", ".join(missing)
            if context:
                message = f"Missing {context} local Ollama configuration: " + ", ".join(missing)
            raise ValueError(message)

        if model != REQUIRED_OLLAMA_MODEL:
            message = (
                "Unsupported Ollama model: "
                f"{model!r}. Expected {REQUIRED_OLLAMA_MODEL!r}."
            )
            if context:
                message = (
                    f"Unsupported {context} Ollama model: "
                    f"{model!r}. Expected {REQUIRED_OLLAMA_MODEL!r}."
                )
            raise ValueError(message)
        if api_base not in ALLOWED_OLLAMA_API_BASES:
            message = (
                "Unsupported Ollama API base: "
                f"{api_base!r}. Expected one of {sorted(ALLOWED_OLLAMA_API_BASES)!r}."
            )
            if context:
                message = (
                    f"Unsupported {context} Ollama API base: "
                    f"{api_base!r}. Expected one of {sorted(ALLOWED_OLLAMA_API_BASES)!r}."
                )
            raise ValueError(message)

        return cls(ollama_model=model, ollama_api_base=api_base)
