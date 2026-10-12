from __future__ import annotations

import argparse
import asyncio
import re

from google.adk.runners import InMemoryRunner
from google.genai import types

from agents.agent_a.agent import build_agent_a

DETERMINISTIC_PROMPT = "Reply with the single word PASS and nothing else."


def _normalize_response(response_text: str) -> str:
    return re.sub(r"\s+", " ", response_text).strip()


def _is_pass_response(response_text: str) -> bool:
    normalized = _normalize_response(response_text)
    return normalized.lower() == "pass"


async def _run_live_probe() -> str:
    agent = build_agent_a()
    runner = InMemoryRunner(agent=agent)
    await runner.session_service.create_session(
        app_name="InMemoryRunner",
        user_id="agent-a-smoke-user",
        session_id="agent-a-smoke-session",
    )

    final_response = ""
    async for event in runner.run_async(
        user_id="agent-a-smoke-user",
        session_id="agent-a-smoke-session",
        new_message=types.Content(
            role="user",
            parts=[types.Part(text=DETERMINISTIC_PROMPT)],
        ),
    ):
        if not event.is_final_response():
            continue
        content = getattr(event, "content", None)
        if content is None:
            continue
        final_parts = []
        for part in getattr(content, "parts", []) or []:
            text = getattr(part, "text", None)
            if text and not getattr(part, "thought", False):
                final_parts.append(text)
        if final_parts:
            final_response = " ".join(final_parts)

    return final_response


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument(
        "--live-local-ollama",
        action="store_true",
        help="Run the single Agent A local Ollama smoke check.",
    )
    args = parser.parse_args(argv)

    if not args.live_local_ollama:
        print("FAIL")
        return 2

    try:
        response_text = asyncio.run(_run_live_probe())
    except Exception:
        print("FAIL")
        return 1

    if _is_pass_response(response_text):
        print("PASS")
        return 0

    print("FAIL")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
