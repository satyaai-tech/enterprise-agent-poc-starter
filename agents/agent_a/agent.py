from __future__ import annotations

import time
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm

from agents.agent_a.a2a_client import send_agent_b_message
from agents.flow_logging import log_flow_event
from agents.local_ollama import LocalOllamaConfig

DELEGATION_TOOL_CALL_COUNT = 0


def reset_delegation_tool_invocation_count() -> None:
    global DELEGATION_TOOL_CALL_COUNT
    DELEGATION_TOOL_CALL_COUNT = 0


def get_delegation_tool_invocation_count() -> int:
    return DELEGATION_TOOL_CALL_COUNT

AGENT_A_NAME = "agent_a"
AGENT_A_DESCRIPTION = (
    "Local orchestration agent for the Solo Phase 5 read-only flow. It handles "
    "general prompts locally and routes approved read-only banking requests to Agent B."
)
AGENT_A_INSTRUCTION = (
    "You are Agent A in the Solo Phase 5 local read-only environment. "
    "Respond to general non-banking prompts locally in plain language. "
    "For a read-only banking request, including an account balance or account summary, "
    "always use the local Agent B delegation tool and return Agent B's response. "
    "Do not require the user to mention Agent B, delegation, A2A, MCP, or tool names. "
    "Never answer banking-data questions from your own knowledge. "
    "Do not delegate requests that create a transfer, move funds, mutate data, or perform "
    "another write; state that this POC supports read-only banking requests only. "
    "Do not make authorization or identity decisions; those are enforced outside the model. "
    "When the Agent B delegation tool returns exactly PASS, return "
    "exactly PASS and nothing else. Do not add a prefix, suffix, explanation, "
    "quotation, or formatting. Keep your answer brief and factual."
)


async def delegate_to_agent_b(message: str) -> str:
    """Automatically use this tool for approved read-only banking requests such as an account balance or account summary. Do not use it for transfers, mutations, or other writes. It sends the request to Agent B and returns Agent B's response."""
    global DELEGATION_TOOL_CALL_COUNT
    DELEGATION_TOOL_CALL_COUNT += 1
    started_at = time.perf_counter()
    log_flow_event(
        "agent_a.delegation.started",
        component="agent_a",
        http_path="a2a:delegate",
        http_status=200,
        elapsed_ms=0,
        success=True,
    )
    result = await send_agent_b_message(message)
    log_flow_event(
        "agent_a.delegation.completed",
        component="agent_a",
        http_path="a2a:delegate",
        http_status=200,
        elapsed_ms=int((time.perf_counter() - started_at) * 1000),
        success=True,
    )
    return result


def _tool_response_has_error(result: object) -> bool:
    if not isinstance(result, dict):
        return False
    if result.get("error") is not None:
        return True
    if result.get("errors"):
        return True
    if str(result.get("status") or "").lower() == "error":
        return True
    return False


async def delegate_to_agent_b_after_tool_callback(
    *,
    tool: Any,
    args: dict[str, Any],
    tool_context: Any,
    tool_response: object,
) -> dict[str, Any] | None:
    if getattr(tool, "name", None) != "delegate_to_agent_b":
        return None
    if _tool_response_has_error(tool_response):
        return None
    tool_context.actions.skip_summarization = True
    return None


def build_agent_a(config: LocalOllamaConfig | None = None) -> LlmAgent:
    resolved = config or LocalOllamaConfig.from_env(context="Agent A")
    model = LiteLlm(model=resolved.model_name, api_base=resolved.ollama_api_base)
    return LlmAgent(
        name=AGENT_A_NAME,
        description=AGENT_A_DESCRIPTION,
        model=model,
        instruction=AGENT_A_INSTRUCTION,
        tools=[delegate_to_agent_b],
        after_tool_callback=delegate_to_agent_b_after_tool_callback,
    )


try:
    root_agent = build_agent_a()
except ValueError:
    root_agent = None
