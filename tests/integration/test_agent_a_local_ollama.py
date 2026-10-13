from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from google.adk.tools.function_tool import FunctionTool
from google.genai import types

from agents.agent_a.agent import AGENT_A_INSTRUCTION, AGENT_A_NAME, build_agent_a
from agents.agent_a.agent import delegate_to_agent_b_after_tool_callback
from agents.agent_a.config import LocalOllamaConfig
from agents.agent_a.smoke import _is_pass_response, _run_live_probe


def test_local_ollama_default_configuration(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3:8b")
    monkeypatch.setenv("OLLAMA_API_BASE", "http://localhost:11434")

    config = LocalOllamaConfig.from_env()

    assert config.ollama_model == "qwen3:8b"
    assert config.ollama_api_base == "http://localhost:11434"
    assert config.model_name == "ollama_chat/qwen3:8b"


def test_provider_prefix_is_ollama_chat(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3:8b")
    monkeypatch.setenv("OLLAMA_API_BASE", "http://localhost:11434")

    config = LocalOllamaConfig.from_env()

    assert config.model_name == "ollama_chat/qwen3:8b"


def test_agent_a_name_and_instruction(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3:8b")
    monkeypatch.setenv("OLLAMA_API_BASE", "http://localhost:11434")

    agent = build_agent_a()

    assert agent.name == AGENT_A_NAME
    assert AGENT_A_NAME in agent.name.lower()
    assert "Agent A" in AGENT_A_INSTRUCTION
    assert "read-only banking request" in AGENT_A_INSTRUCTION.lower()
    assert "always use the local Agent B delegation tool" in AGENT_A_INSTRUCTION
    assert "Do not require the user to mention Agent B" in AGENT_A_INSTRUCTION
    assert "create a transfer" in AGENT_A_INSTRUCTION
    assert (
        "When the Agent B delegation tool returns exactly PASS, return exactly PASS and nothing else. "
        "Do not add a prefix, suffix, explanation, quotation, or formatting."
    ) in AGENT_A_INSTRUCTION


def test_agent_a_registers_a2a_delegation_tool(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3:8b")
    monkeypatch.setenv("OLLAMA_API_BASE", "http://localhost:11434")

    agent = build_agent_a()
    tool_names = {getattr(tool, "__name__", None) for tool in agent.tools}

    assert "delegate_to_agent_b" in tool_names


def test_agent_a_registers_delegation_after_tool_callback(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3:8b")
    monkeypatch.setenv("OLLAMA_API_BASE", "http://localhost:11434")

    agent = build_agent_a()

    assert any(
        callback.__name__ == "delegate_to_agent_b_after_tool_callback"
        for callback in agent.canonical_after_tool_callbacks
    )


def test_agent_a_tool_calls_mocked_a2a_transport(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3:8b")
    monkeypatch.setenv("OLLAMA_API_BASE", "http://localhost:11434")

    tool = FunctionTool(build_agent_a().tools[0])

    with patch("agents.agent_a.agent.send_agent_b_message", AsyncMock(return_value="PASS")) as mock_send:
        result = asyncio.run(
            tool.run_async(
                args={"message": "Delegate to Agent B: Reply with PASS and nothing else."},
                tool_context=None,
            )
        )

    assert result == "PASS"
    mock_send.assert_awaited_once_with("Delegate to Agent B: Reply with PASS and nothing else.")


def test_delegate_to_agent_b_after_tool_callback_sets_skip_summarization_on_success():
    tool = SimpleNamespace(name="delegate_to_agent_b")
    tool_context = SimpleNamespace(actions=SimpleNamespace(skip_summarization=None))
    result = {"result": "Balance is 12345.67"}

    returned = asyncio.run(
        delegate_to_agent_b_after_tool_callback(
            tool=tool,
            args={"message": "delegate now"},
            tool_context=tool_context,
            tool_response=result,
        )
    )

    assert returned is None
    assert tool_context.actions.skip_summarization is True
    assert result == {"result": "Balance is 12345.67"}


def test_delegate_to_agent_b_after_tool_callback_does_not_set_skip_summarization_on_error():
    tool = SimpleNamespace(name="delegate_to_agent_b")
    tool_context = SimpleNamespace(actions=SimpleNamespace(skip_summarization=None))
    result = {"error": {"message": "tool failed"}}

    returned = asyncio.run(
        delegate_to_agent_b_after_tool_callback(
            tool=tool,
            args={"message": "delegate now"},
            tool_context=tool_context,
            tool_response=result,
        )
    )

    assert returned is None
    assert tool_context.actions.skip_summarization is None
    assert result == {"error": {"message": "tool failed"}}


def test_delegate_to_agent_b_after_tool_callback_ignores_unrelated_tools():
    tool = SimpleNamespace(name="unrelated_tool")
    tool_context = SimpleNamespace(actions=SimpleNamespace(skip_summarization=None))
    result = {"result": "leave me alone"}

    returned = asyncio.run(
        delegate_to_agent_b_after_tool_callback(
            tool=tool,
            args={"message": "delegate now"},
            tool_context=tool_context,
            tool_response=result,
        )
    )

    assert returned is None
    assert tool_context.actions.skip_summarization is None
    assert result == {"result": "leave me alone"}


def test_missing_configuration_fails_clearly(monkeypatch):
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    monkeypatch.delenv("OLLAMA_API_BASE", raising=False)

    with pytest.raises(ValueError, match="Missing Agent A local Ollama configuration"):
        build_agent_a()


def test_default_test_suite_mocks_model_boundary(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3:8b")
    monkeypatch.setenv("OLLAMA_API_BASE", "http://localhost:11434")

    with patch("agents.agent_a.agent.LiteLlm") as mock_litellm, patch(
        "agents.agent_a.agent.LlmAgent"
    ) as mock_llm_agent:
        build_agent_a()

    mock_litellm.assert_called_once_with(
        model="ollama_chat/qwen3:8b", api_base="http://localhost:11434"
    )
    mock_llm_agent.assert_called_once()


def test_smoke_runner_uses_adk_runner_and_requires_exact_pass(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3:8b")
    monkeypatch.setenv("OLLAMA_API_BASE", "http://localhost:11434")

    async def fake_run_async(*, user_id, session_id, new_message, **kwargs):
        yield SimpleNamespace(
            is_final_response=lambda: False,
            content=None,
        )
        yield SimpleNamespace(
            is_final_response=lambda: True,
            content=types.Content(
                role="model",
                parts=[
                    types.Part(text="PASS", thought=False),
                ],
            ),
        )

    with patch("agents.agent_a.smoke.InMemoryRunner") as mock_runner:
        runner = MagicMock()
        runner.session_service.create_session = AsyncMock()
        runner.run_async = fake_run_async
        mock_runner.return_value = runner

        assert _is_pass_response("PASS") is True
        assert _is_pass_response("pass") is True
        assert _is_pass_response("PASS with extra") is False
        assert _is_pass_response("PASS\nextra") is False

        result = asyncio.run(_run_live_probe())
        assert result == "PASS"

        mock_runner.assert_called_once()
        runner.session_service.create_session.assert_called_once()
