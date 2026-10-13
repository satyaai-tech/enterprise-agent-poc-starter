from __future__ import annotations

from contextvars import ContextVar, Token


DELEGATED_TOKEN_A: ContextVar[str | None] = ContextVar("agent_a_delegated_token_a", default=None)


def set_delegated_token_a(token_a: str | None) -> Token[str | None]:
    return DELEGATED_TOKEN_A.set(token_a)


def get_delegated_token_a() -> str | None:
    return DELEGATED_TOKEN_A.get()


def reset_delegated_token_a(token: Token[str | None]) -> None:
    DELEGATED_TOKEN_A.reset(token)


__all__ = ["DELEGATED_TOKEN_A", "get_delegated_token_a", "reset_delegated_token_a", "set_delegated_token_a"]
