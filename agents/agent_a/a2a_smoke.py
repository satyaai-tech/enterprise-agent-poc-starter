from __future__ import annotations

import argparse
import asyncio
import re
import time

from google.adk.runners import InMemoryRunner
from google.genai import types

from agents.agent_a.a2a_client import get_a2a_client_invocation_count, reset_a2a_client_invocation_count
from agents.agent_a.agent import (
    build_agent_a,
    get_delegation_tool_invocation_count,
    reset_delegation_tool_invocation_count,
)
from agents.flow_logging import log_flow_event

DELEGATION_PROMPT = "Delegate to Agent B: Reply with PASS and nothing else."


def _normalize_response(response_text: str) -> str:
    return re.sub(r"\s+", " ", response_text).strip()


async def _run_live_probe() -> str:
    reset_delegation_tool_invocation_count()
    reset_a2a_client_invocation_count()
    started_at = time.perf_counter()
    log_flow_event(
        "agent_a.request.received",
        component="agent_a",
        http_path="inmemory:run",
        http_status=200,
        elapsed_ms=0,
        success=True,
    )
    agent = build_agent_a()
    runner = InMemoryRunner(agent=agent)
    await runner.session_service.create_session(
        app_name="InMemoryRunner",
        user_id="agent-a-a2a-smoke-user",
        session_id="agent-a-a2a-smoke-session",
    )

    final_message = ""
    async for event in runner.run_async(
        user_id="agent-a-a2a-smoke-user",
        session_id="agent-a-a2a-smoke-session",
        new_message=types.Content(
            role="user",
            parts=[types.Part(text=DELEGATION_PROMPT)],
        ),
    ):
        if not event.is_final_response():
            continue
        content = getattr(event, "content", None)
        if content is None:
            continue
        for part in getattr(content, "parts", []) or []:
            text = getattr(part, "text", None)
            if text and not getattr(part, "thought", False):
                final_message = _normalize_response(text)
                break

    if not final_message:
        raise ValueError("Agent A returned no final message")
    if get_delegation_tool_invocation_count() != 1:
        raise ValueError("delegate_to_agent_b did not run exactly once")
    if get_a2a_client_invocation_count() != 1:
        raise ValueError("A2A client did not run exactly once")
    if final_message.lower() != "pass":
        raise ValueError("Agent A did not return the delegated PASS result")

    elapsed_ms = int((time.perf_counter() - started_at) * 1000)
    log_flow_event(
        "agent_a.response.completed",
        component="agent_a",
        http_path="inmemory:run",
        http_status=200,
        elapsed_ms=elapsed_ms,
        success=True,
    )
    return final_message


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument(
        "--live-local-a2a",
        action="store_true",
        help="Run the direct Agent A -> local Agent B A2A smoke check.",
    )
    args = parser.parse_args(argv)

    if not args.live_local_a2a:
        print("FAIL")
        return 2

    try:
        response_text = asyncio.run(_run_live_probe())
    except Exception:
        print("FAIL")
        return 1

    normalized = _normalize_response(response_text)
    if normalized.lower() == "pass":
        print("PASS")
        return 0

    print("FAIL")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
