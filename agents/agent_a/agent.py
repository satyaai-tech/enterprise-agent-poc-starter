from __future__ import annotations

import time

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
    "Local Agent A for the Solo Phase 4 slice. It responds to user prompts using "
    "the local Ollama model and does not make banking, authorization, or delegated "
    "identity decisions."
)
AGENT_A_INSTRUCTION = (
    "You are Agent A in the Solo Phase 4 local test environment. "
    "Respond to the current prompt in plain language. "
    "Do not make banking, authorization, or identity decisions. "
    "If the user explicitly asks you to delegate a message to Agent B over the "
    "local A2A endpoint, use the local Agent B delegation tool and return Agent "
    "B's response. When the Agent B delegation tool returns exactly PASS, return "
    "exactly PASS and nothing else. Do not add a prefix, suffix, explanation, "
    "quotation, or formatting. Otherwise, do not perform A2A, MCP, gateway, or "
    "tool operations. Keep your answer brief and factual."
)


async def delegate_to_agent_b(message: str) -> str:
    """Use this tool when the user explicitly asks Agent A to delegate a message to Agent B over the local A2A endpoint. It sends the message to Agent B and returns Agent B's response."""
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


def build_agent_a(config: LocalOllamaConfig | None = None) -> LlmAgent:
    resolved = config or LocalOllamaConfig.from_env(context="Agent A")
    model = LiteLlm(model=resolved.model_name, api_base=resolved.ollama_api_base)
    return LlmAgent(
        name=AGENT_A_NAME,
        description=AGENT_A_DESCRIPTION,
        model=model,
        instruction=AGENT_A_INSTRUCTION,
        tools=[delegate_to_agent_b],
    )


try:
    root_agent = build_agent_a()
except ValueError:
    root_agent = None
