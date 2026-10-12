from __future__ import annotations

import argparse
import asyncio
import json
import re
from typing import Any

import httpx

A2A_BASE_URL = "http://127.0.0.1:8001"
A2A_AGENT_CARD_URL = f"{A2A_BASE_URL}/.well-known/agent-card.json"
A2A_RPC_URL = f"{A2A_BASE_URL}/"


def _sanitize_failure(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text[:200] if text else "FAIL"


def _extract_first_text(value: Any) -> str:
    if isinstance(value, str):
        text = value.strip()
        return text
    if isinstance(value, dict):
        for key in ("text", "content", "message", "response"):
            if key in value:
                extracted = _extract_first_text(value[key])
                if extracted:
                    return extracted
        for nested in value.values():
            extracted = _extract_first_text(nested)
            if extracted:
                return extracted
    if isinstance(value, list):
        for item in value:
            extracted = _extract_first_text(item)
            if extracted:
                return extracted
    return ""


async def _run_live_probe() -> str:
    async with httpx.AsyncClient(timeout=30.0) as client:
        agent_card_response = await client.get(A2A_AGENT_CARD_URL)
        agent_card_response.raise_for_status()
        card = agent_card_response.json()
        if not isinstance(card, dict) or not card.get("name"):
            raise ValueError("Agent card missing name")

        payload = {
            "jsonrpc": "2.0",
            "id": "agent-b-local-a2a-smoke",
            "method": "message/send",
            "params": {
                "message": {
                    "messageId": "agent-b-local-a2a-smoke-message",
                    "role": "user",
                    "parts": [{"kind": "text", "text": "Reply with PASS and nothing else."}],
                }
            },
        }
        response = await client.post(A2A_RPC_URL, json=payload)
        response.raise_for_status()
        response_data = response.json()

    extracted = _extract_first_text(response_data)
    if not extracted:
        raise ValueError("empty A2A response")
    return extracted


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument(
        "--live-local-a2a",
        action="store_true",
        help="Run the Agent B local A2A smoke check.",
    )
    args = parser.parse_args(argv)

    if not args.live_local_a2a:
        print("FAIL")
        return 2

    try:
        response_text = asyncio.run(_run_live_probe())
    except Exception as exc:
        print("FAIL")
        return 1

    if response_text and response_text.strip():
        print("PASS")
        return 0

    print("FAIL")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
