from __future__ import annotations

import json
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
NOTEBOOK_PATH = REPO_ROOT / "notebooks" / "phase-5-gradio-read-only-demo.ipynb"


def _notebook() -> dict:
    return json.loads(NOTEBOOK_PATH.read_text(encoding="utf-8"))


def _code_cells() -> list[dict]:
    return [cell for cell in _notebook().get("cells", []) if cell.get("cell_type") == "code"]


def _code() -> str:
    return "\n".join("".join(cell.get("source", [])) for cell in _code_cells())


def test_gradio_notebook_is_clean_and_uses_project_kernel() -> None:
    notebook = _notebook()
    assert notebook["metadata"]["kernelspec"]["name"] == "enterprise-agent-poc"
    for cell in _code_cells():
        assert cell.get("execution_count") is None
        assert cell.get("outputs", []) == []


def test_gradio_ui_is_local_only_and_has_no_public_share() -> None:
    code = _code()
    assert 'server_name="127.0.0.1"' in code
    assert "share=False" in code
    assert "inline=False" in code
    assert "inbrowser=True" in code
    assert "share=True" not in code
    assert "0.0.0.0" not in code


def test_gradio_ui_uses_device_code_for_token_a_only() -> None:
    code = _code()
    assert "msal.PublicClientApplication" in code
    assert "initiate_device_flow" in code
    assert "acquire_token_by_device_flow" in code
    assert 'os.getenv("ENTRA_NOTEBOOK_CLIENT_ID"' in code
    assert 'os.getenv("ENTRA_AGENT_A_SCOPE"' in code
    assert "TOKEN_B_FILE" not in code
    assert "TOKEN_C_FILE" not in code
    assert re.search(r"\btoken_[bc]\b", code, flags=re.IGNORECASE) is None


def test_gradio_ui_never_displays_or_logs_token_a() -> None:
    code = _code()
    assert "print(token_a" not in code.lower()
    assert "gr.Textbox(value=token_a" not in code
    assert "print(events)" not in code
    assert "json.dumps(events)" not in code


def test_gradio_ui_accepts_a_user_prompt_without_action_buttons() -> None:
    code = _code()
    assert "def run_agent_prompt" in code
    assert 'prompt_input = gr.Textbox(' in code
    assert "prompt_input.submit(" in code
    assert '"parts": [{"text": prompt}]' in code
    assert "gr.Button(" not in code
    assert "chat_history = gr.Chatbot(" in code
    assert 'layout="bubble"' in code
    assert "gr.ChatInterface" not in code
    assert "create_transfer" not in code


def test_gradio_ui_uses_a_multiline_prompt_area_with_read_and_transfer_examples() -> None:
    code = _code()
    assert "gr.Dropdown(" not in code
    assert "select_prompt_template" not in code
    assert '"Read example: What is the balance for synthetic account acct-1001?' in code
    assert '"Transfer example: Transfer 25.00 from synthetic account acct-1001 to acct-2002.' in code
    assert "lines=4" in code
    assert "max_lines=8" in code
    assert 'submit_btn="Send"' in code
    assert "Enter adds a new line. Select Send to submit the message." in code


def test_gradio_ui_starts_entra_sign_in_and_sends_all_prompts_to_agent_a() -> None:
    code = _code()
    assert "demo.load(" in code
    assert "fn=sign_in_with_entra" in code
    assert "write_markers" not in code
    assert '"parts": [{"text": prompt}]' in code
    assert "writes are refused by the Phase 5 agent policy" in code


def test_gradio_ui_renders_a_safe_clickable_microsoft_device_login_link() -> None:
    code = _code()
    assert "def _device_sign_in_html" in code
    assert 'parsed.scheme != "https"' in code
    assert '"login.microsoft.com"' in code
    assert '"login.microsoftonline.com"' in code
    assert "target='_blank'" in code
    assert "rel='noopener noreferrer'" in code
    assert "html.escape(verification_uri, quote=True)" in code
    assert "html.escape(user_code)" in code
    assert "sign_in_status = gr.HTML()" in code


def test_gradio_ui_does_not_manage_docker_or_processes() -> None:
    code = _code().lower()
    for fragment in ("docker compose", "subprocess", "popen(", "system("):
        assert fragment not in code


def test_gradio_ui_accepts_local_or_completed_delegated_responses_and_rejects_write_tools() -> None:
    code = _code()
    assert 'delegated_call = "delegate_to_agent_b" in tool_calls' in code
    assert "if delegated_call != delegated_response" in code
    assert '_tool_name(payload) == "delegate_to_agent_b"' in code
    assert 'set(tool_calls + tool_responses) - {"delegate_to_agent_b", "get_account_summary"}' in code
    assert '"balance" in prompt.lower() and "acct-1001" in prompt.lower()' in code
    assert 'headers["X-Flow-ID"] = flow_id' in code


def test_gradio_ui_streams_safe_client_observable_progress_updates() -> None:
    code = _code()
    assert "def _render_activity" in code
    assert 'lines = [f"✅ {step}" for step in completed]' in code
    assert 'lines.append(f"⏳ {current}")' in code
    assert 'lines.append(f"❌ {error}")' in code
    assert 'completed = ["1/5 Prompt validated."]' in code
    assert "2/5 Preparing the protected Agent A conversation session" in code
    assert "3/5 Agent A is processing the request" in code
    assert "4/5 Validating response structure and tool boundaries" in code
    assert "5/5 Finalizing the chat response" in code
    assert "5/5 Request completed successfully." in code
    assert "_render_activity(completed, flow_id=flow_id)" in code
    assert 'label="Live request activity"' in code
    assert "agent_b_logs" not in code
    assert "banking_mcp_logs" not in code


def test_gradio_chat_preserves_history_and_reuses_the_agent_session() -> None:
    code = _code()
    assert "def _normalize_chat_history" in code
    assert "def _replace_assistant_message" in code
    assert 'agent_session_state = gr.State(value=None)' in code
    assert '"role": "user", "content": prompt' in code
    assert '"role": "assistant", "content": "Working on your request..."' in code
    assert "Existing Agent A conversation session reused." in code
    assert "inputs=[prompt_input, chat_history, token_a_state, agent_session_state]" in code
    assert "outputs=[chat_history, request_status, prompt_input, agent_session_state]" in code
