from __future__ import annotations

"""Local Agent B A2A service.

Run locally with:

PYTHONPATH="$PWD" \
OLLAMA_MODEL=qwen3:8b \
OLLAMA_API_BASE=http://localhost:11434 \
uv run uvicorn agents.agent_b.a2a_server:a2a_app \
  --host 127.0.0.1 \
  --port 8001
"""

import asyncio
import os
import time
import uuid
from functools import wraps

from google.adk.a2a.utils.agent_card_builder import AgentCardBuilder
from google.adk.a2a.utils.agent_to_a2a import to_a2a

from agents.flow_logging import extract_raw_user_identity, get_flow_id, log_flow_event, set_flow_id
from agents.agent_b.delegated_token_context import reset_delegated_token_b, set_delegated_token_b
from agents.agent_b.agent import build_agent_b

A2A_HOST = os.getenv("A2A_HOST", "127.0.0.1")
A2A_PORT = int(os.getenv("A2A_PORT", "8001"))
A2A_PUBLIC_URL = os.getenv("A2A_PUBLIC_URL")
A2A_AGENT_CARD_URL = os.getenv(
    "A2A_AGENT_CARD_URL",
    f"http://{A2A_HOST}:{A2A_PORT}/.well-known/agent-card.json",
)


def _build_public_agent_card(agent):
    async def _make_card():
        public_url = A2A_PUBLIC_URL.rstrip("/") + "/"
        card = await AgentCardBuilder(
            agent=agent,
            rpc_url=public_url,
        ).build()
        if hasattr(card, "supported_interfaces") and len(card.supported_interfaces) > 0:
            for interface in card.supported_interfaces:
                interface.url = public_url
        return card

    return asyncio.run(_make_card())


def _with_a2a_flow_logging(app):
    @wraps(app)
    async def wrapped(scope, receive, send):
        if scope.get("type") != "http":
            await app(scope, receive, send)
            return

        headers = {key.decode("utf-8", "ignore").lower(): value.decode("utf-8", "ignore") for key, value in scope.get("headers", [])}
        flow_id = headers.get("x-flow-id") or uuid.uuid4().hex[:12]
        set_flow_id(flow_id)
        path = scope.get("path", "/")
        authorization = headers.get("authorization", "").strip()
        delegated_token = None
        if path != "/.well-known/agent-card.json" and authorization.lower().startswith("bearer "):
            delegated_token = authorization.split(" ", 1)[1].strip() or None
        context_token = set_delegated_token_b(delegated_token)
        if delegated_token:
            identity_fields = {}
            if os.getenv("POC_LOG_RAW_USER_ID") == "true":
                identity_fields = extract_raw_user_identity(token=delegated_token)
            log_flow_event(
                "agent_b.delegated_token.received",
                component="agent_b",
                flow_id=flow_id,
                http_path=path,
                http_status=200,
                elapsed_ms=0,
                success=True,
                delegated_token_present=True,
                **identity_fields,
            )
        started_at = time.perf_counter()
        log_flow_event(
            "agent_b.a2a.request.received",
            component="agent_b",
            flow_id=flow_id,
            http_path=path,
            http_status=200,
            elapsed_ms=0,
            success=True,
        )

        async def send_with_logging(message):
            if message.get("type") == "http.response.start":
                elapsed_ms = int((time.perf_counter() - started_at) * 1000)
                log_flow_event(
                    "agent_b.a2a.response.completed",
                    component="agent_b",
                    flow_id=flow_id,
                    http_path=path,
                    http_status=message.get("status", 200),
                    elapsed_ms=elapsed_ms,
                    success=message.get("status", 200) < 400,
                )
            await send(message)

        try:
            await app(scope, receive, send_with_logging)
        finally:
            reset_delegated_token_b(context_token)

    return wrapped


def create_a2a_app():
    agent = build_agent_b()
    kwargs = {
        "host": A2A_HOST,
        "port": A2A_PORT,
        "protocol": "http",
    }
    if A2A_PUBLIC_URL:
        kwargs["agent_card"] = _build_public_agent_card(agent)
    app = to_a2a(agent, **kwargs)
    if isinstance(app, str):
        return app
    return _with_a2a_flow_logging(app)

try:
    a2a_app = create_a2a_app()
except ValueError:
    a2a_app = None

__all__ = ["a2a_app", "A2A_HOST", "A2A_PORT", "A2A_AGENT_CARD_URL", "create_a2a_app"]
