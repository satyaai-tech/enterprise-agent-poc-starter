from __future__ import annotations

import os
import time
import uuid
from typing import Any

import httpx

from a2a.client import A2ACardResolver, ClientConfig, create_client
from a2a.types.a2a_pb2 import Message, Part, Role, SendMessageRequest
from a2a.utils.constants import TransportProtocol

from agents.flow_logging import get_flow_id, log_flow_event, set_flow_id
from agents.agent_a.token_b_provider import resolve_agent_a_token_b

AGENT_B_A2A_URL = os.getenv("AGENT_B_A2A_URL", "http://127.0.0.1:8001")
A2A_CLIENT_INVOCATION_COUNT = 0


def reset_a2a_client_invocation_count() -> None:
    global A2A_CLIENT_INVOCATION_COUNT
    A2A_CLIENT_INVOCATION_COUNT = 0


def get_a2a_client_invocation_count() -> int:
    return A2A_CLIENT_INVOCATION_COUNT


def _ensure_flow_id() -> str:
    flow_id = get_flow_id()
    if flow_id:
        return flow_id
    flow_id = uuid.uuid4().hex[:12]
    set_flow_id(flow_id)
    return flow_id


def _public_a2a_headers() -> dict[str, str]:
    return {"X-Flow-ID": _ensure_flow_id()}


async def _protected_a2a_headers() -> dict[str, str]:
    headers = _public_a2a_headers()
    headers["Authorization"] = f"Bearer {await resolve_agent_a_token_b()}"
    return headers


def _is_adk_thought(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, dict):
        metadata = value.get("metadata")
        if isinstance(metadata, dict):
            adk_thought = metadata.get("adk_thought")
            if isinstance(adk_thought, bool):
                return adk_thought
            if isinstance(adk_thought, dict):
                return bool(adk_thought.get("bool_value"))
        adk_thought = value.get("adk_thought")
        if isinstance(adk_thought, bool):
            return adk_thought
        if isinstance(adk_thought, dict):
            return bool(adk_thought.get("bool_value"))
        return False
    metadata = getattr(value, "metadata", None)
    if metadata is None:
        return False
    fields = getattr(metadata, "fields", None)
    if fields is None:
        return False
    if hasattr(fields, "get"):
        adk_thought = fields.get("adk_thought")
        if adk_thought is None:
            return False
        return bool(getattr(adk_thought, "bool_value", False))
    for key, field_value in getattr(fields, "items", lambda: [])():
        if key == "adk_thought":
            return bool(getattr(field_value, "bool_value", False))
    return False


def _extract_first_text(value: Any) -> str:
    if value is None:
        return ""

    if isinstance(value, str):
        text = value.strip()
        return text
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").strip()

    if isinstance(value, dict):
        for key in ("text", "content", "message", "response", "result"):
            if key in value:
                extracted = _extract_first_text(value[key])
                if extracted:
                    return extracted
        for nested in value.values():
            extracted = _extract_first_text(nested)
            if extracted:
                return extracted
        return ""

    if isinstance(value, (list, tuple)):
        for item in value:
            extracted = _extract_first_text(item)
            if extracted:
                return extracted
        return ""

    if hasattr(value, "artifacts"):
        for artifact in value.artifacts:
            for part in getattr(artifact, "parts", []):
                if _is_adk_thought(part):
                    continue
                if hasattr(part, "text") and getattr(part, "text", "").strip():
                    return getattr(part, "text").strip()
        return ""
    if hasattr(value, "history"):
        for message in value.history:
            for part in getattr(message, "parts", []):
                if _is_adk_thought(part):
                    continue
                if hasattr(part, "text") and getattr(part, "text", "").strip():
                    return getattr(part, "text").strip()
        return ""
    if hasattr(value, "parts"):
        for part in value.parts:
            if _is_adk_thought(part):
                continue
            if hasattr(part, "text") and getattr(part, "text", "").strip():
                return getattr(part, "text").strip()
        return ""
    if hasattr(value, "HasField") and value.HasField("task"):
        return _extract_first_text(getattr(value, "task"))
    if hasattr(value, "HasField") and value.HasField("message"):
        return _extract_first_text(getattr(value, "message"))
    if hasattr(value, "status"):
        return _extract_first_text(getattr(value, "status"))
    if hasattr(value, "task"):
        return _extract_first_text(getattr(value, "task"))
    if hasattr(value, "message"):
        return _extract_first_text(getattr(value, "message"))
    if hasattr(value, "text"):
        text = getattr(value, "text")
        if isinstance(text, str) and text.strip():
            return text.strip()
    return ""


async def fetch_agent_b_agent_card(base_url: str = AGENT_B_A2A_URL) -> Any:
    flow_id = _ensure_flow_id()
    started_at = time.perf_counter()
    headers = _public_a2a_headers()
    async with httpx.AsyncClient(timeout=30.0, headers=headers) as http_client:
        resolver = A2ACardResolver(http_client, base_url)
        card = await resolver.get_agent_card()
    log_flow_event(
        "a2a.agent_card.resolved",
        component="agent_a",
        flow_id=flow_id,
        http_path="/.well-known/agent-card.json",
        http_status=200,
        elapsed_ms=int((time.perf_counter() - started_at) * 1000),
        success=True,
    )
    return card


async def send_agent_b_message(message_text: str, base_url: str = AGENT_B_A2A_URL) -> str:
    global A2A_CLIENT_INVOCATION_COUNT
    if not message_text or not message_text.strip():
        raise ValueError("message_text must be a non-empty string")

    flow_id = _ensure_flow_id()
    await fetch_agent_b_agent_card(base_url)
    started_at = time.perf_counter()
    log_flow_event(
        "a2a.message.sending",
        component="agent_a",
        flow_id=flow_id,
        http_path="a2a:send_message",
        http_status=200,
        elapsed_ms=0,
        success=True,
    )
    A2A_CLIENT_INVOCATION_COUNT += 1
    http_client = httpx.AsyncClient(timeout=180.0, headers=await _protected_a2a_headers())
    client_config = ClientConfig(
        streaming=False,
        httpx_client=http_client,
        supported_protocol_bindings=[
            TransportProtocol.JSONRPC,
            TransportProtocol.HTTP_JSON,
        ],
    )
    client = await create_client(base_url, client_config=client_config)
    try:
        request = SendMessageRequest(
            message=Message(
                message_id=str(uuid.uuid4()),
                role=Role.ROLE_USER,
                parts=[Part(text=message_text.strip())],
            )
        )

        async for event in client.send_message(request):
            extracted = _extract_first_text(event)
            if extracted:
                log_flow_event(
                    "a2a.message.response_received",
                    component="agent_a",
                    flow_id=flow_id,
                    http_path="a2a:send_message",
                    http_status=200,
                    elapsed_ms=int((time.perf_counter() - started_at) * 1000),
                    success=True,
                )
                return extracted

        raise ValueError("Agent B returned no text in its A2A response")
    finally:
        await client.close()
        await http_client.aclose()


__all__ = [
    "AGENT_B_A2A_URL",
    "fetch_agent_b_agent_card",
    "send_agent_b_message",
]
