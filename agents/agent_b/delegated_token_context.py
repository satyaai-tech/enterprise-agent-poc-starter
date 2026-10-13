from __future__ import annotations

from contextvars import ContextVar, Token

DELEGATED_TOKEN_B: ContextVar[str | None] = ContextVar("agent_b_delegated_token_b", default=None)


def set_delegated_token_b(token_b: str | None) -> Token[str | None]:
    return DELEGATED_TOKEN_B.set(token_b)


def get_delegated_token_b() -> str | None:
    token_b = DELEGATED_TOKEN_B.get()
    if isinstance(token_b, str) and token_b.strip():
        return token_b
    return None


def reset_delegated_token_b(token: Token[str | None]) -> None:
    DELEGATED_TOKEN_B.reset(token)


__all__ = ["DELEGATED_TOKEN_B", "get_delegated_token_b", "reset_delegated_token_b", "set_delegated_token_b"]