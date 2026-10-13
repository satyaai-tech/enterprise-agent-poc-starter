from __future__ import annotations

import json
import os
import uuid
from typing import Any

import httpx

from agents.flow_logging import extract_raw_user_identity, get_flow_id, log_flow_event
from agents.agent_b.token_c_provider import TokenCResolutionError, resolve_agent_b_token_c

MCP_GATEWAY_URL = os.getenv("BANKING_MCP_URL", "http://agentgateway:8082/mcp")
MCP_PROTOCOL_VERSION = "2025-03-26"


def _mcp_headers(*, token: str, session_id: str | None = None, flow_id: str | None = None) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
        "X-Flow-ID": flow_id or get_flow_id(),
    }
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    return headers


def _extract_mcp_text(result: Any) -> str:
    if not isinstance(result, dict):
        return ""
    if isinstance(result.get("structuredContent"), dict):
        structured = result["structuredContent"]
        if isinstance(structured.get("balance"), (int, float)):
            return f"Balance is {float(structured['balance']):.2f}"
    content = result.get("content") or []
    if isinstance(content, list):
        for entry in content:
            if isinstance(entry, dict) and isinstance(entry.get("text"), str):
                return entry["text"]
    return ""


def _parse_mcp_payload(raw: str) -> dict[str, object]:
    text = raw.strip()
    if not text:
        raise ValueError("MCP response payload is empty")

    candidates = []
    saw_data_line = False
    for line in text.splitlines():
        stripped_line = line.strip()
        if not stripped_line.startswith("data:"):
            continue
        saw_data_line = True
        candidate = stripped_line[len("data:") :].strip()
        if not candidate or candidate == "[DONE]":
            continue
        candidates.append(candidate)

    if candidates:
        for candidate in reversed(candidates):
            try:
                payload = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                raise ValueError("MCP response payload must be a JSON object")
            return payload
        raise ValueError("MCP response payload is malformed")

    if saw_data_line:
        raise ValueError("MCP response payload is empty")

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("MCP response payload is malformed") from exc
    if not isinstance(payload, dict):
        raise ValueError("MCP response payload must be a JSON object")
    return payload


async def get_account_summary(account_id: str) -> str:
    """Read an account balance via the local MCP gateway using Token C."""
    flow_id = get_flow_id()
    try:
        token = await resolve_agent_b_token_c()
        identity_fields = {}
        if os.getenv("POC_LOG_RAW_USER_ID") == "true":
            identity_fields = extract_raw_user_identity(token=token)
        log_flow_event("mcp_initialize_start", "agent-b.mcp_client", flow_id=flow_id, http_path="/mcp", success=True, **identity_fields)

        async with httpx.AsyncClient(timeout=30.0) as client:
            init_payload = {
                "jsonrpc": "2.0",
                "id": f"init-{uuid.uuid4().hex[:12]}",
                "method": "initialize",
                "params": {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "agent-b", "version": "1.0.0"},
                },
            }
            initialize_response = await client.post(MCP_GATEWAY_URL, json=init_payload, headers=_mcp_headers(token=token, flow_id=flow_id))
            initialize_response.raise_for_status()
            initialize_body = _parse_mcp_payload(initialize_response.text)
            if initialize_body.get("error") is not None:
                raise ValueError("MCP initialize failed")
            initialize_result = initialize_body.get("result")
            if not isinstance(initialize_result, dict):
                raise ValueError("MCP initialize response is invalid")
            session_id = initialize_response.headers.get("Mcp-Session-Id") or initialize_response.headers.get("mcp-session-id")
            if not session_id:
                raise RuntimeError("MCP initialize response missing session id")

            notification_payload = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
            notification_response = await client.post(MCP_GATEWAY_URL, json=notification_payload, headers=_mcp_headers(token=token, session_id=session_id, flow_id=flow_id))
            if notification_response.status_code >= 400:
                raise RuntimeError("MCP notifications/initialized failed")

            log_flow_event("mcp_initialized", "agent-b.mcp_client", flow_id=flow_id, http_path="/mcp", success=True)

            tools_list_payload = {"jsonrpc": "2.0", "method": "tools/list", "params": {}, "id": f"list-{uuid.uuid4().hex[:12]}"}
            tools_list_response = await client.post(MCP_GATEWAY_URL, json=tools_list_payload, headers=_mcp_headers(token=token, session_id=session_id, flow_id=flow_id))
            tools_list_response.raise_for_status()
            tools_list_body = _parse_mcp_payload(tools_list_response.text)
            if tools_list_body.get("error") is not None:
                raise ValueError("MCP tools/list failed")
            tools_list_result = tools_list_body.get("result")
            if not isinstance(tools_list_result, dict):
                raise ValueError("MCP tools/list response is invalid")
            tools = tools_list_result.get("tools")
            if not isinstance(tools, list):
                raise ValueError("MCP tools/list response is invalid")
            tool_names = [tool.get("name") for tool in tools if isinstance(tool, dict)]
            if "get_account_summary" not in tool_names:
                raise ValueError("MCP tools/list does not expose get_account_summary")
            if "create_transfer" in tool_names:
                raise ValueError("MCP tools/list exposes create_transfer")

            log_flow_event("mcp_tools_discovered", "agent-b.mcp_client", flow_id=flow_id, http_path="/mcp", success=True)

            call_payload = {
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {"name": "get_account_summary", "arguments": {"account_id": account_id}},
                "id": f"call-{uuid.uuid4().hex[:12]}",
            }
            log_flow_event("mcp_tool_call_start", "agent-b.mcp_client", flow_id=flow_id, http_path="/mcp", success=True)
            call_response = await client.post(MCP_GATEWAY_URL, json=call_payload, headers=_mcp_headers(token=token, session_id=session_id, flow_id=flow_id))
            call_response.raise_for_status()
            call_body = _parse_mcp_payload(call_response.text)
            if call_body.get("error") is not None:
                raise ValueError("MCP tool call failed")
            result = call_body.get("result")
            summary_text = _extract_mcp_text(result)
            if not summary_text:
                raise ValueError("MCP tool call response is missing summary text")
            log_flow_event("mcp_tool_call_complete", "agent-b.mcp_client", flow_id=flow_id, http_path="/mcp", success=True)
            return summary_text
    except TokenCResolutionError as exc:
        log_flow_event(
            "mcp_failure",
            "agent-b.mcp_client",
            flow_id=flow_id,
            http_path="/mcp",
            success=False,
        )
        raise RuntimeError(str(exc)) from exc
    except Exception:
        log_flow_event("mcp_failure", "agent-b.mcp_client", flow_id=flow_id, http_path="/mcp", success=False)
        raise


__all__ = ["get_account_summary", "MCP_GATEWAY_URL"]
