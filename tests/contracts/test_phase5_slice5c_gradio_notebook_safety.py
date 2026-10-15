from __future__ import annotations

import json
import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
NOTEBOOK_PATH = REPO_ROOT / "notebooks" / "phase-5-slice-5c-gradio-user-authorization.ipynb"
APP_PATH = REPO_ROOT / "notebooks" / "phase5_slice5c_gradio_app.py"


def _notebook() -> dict:
    return json.loads(NOTEBOOK_PATH.read_text(encoding="utf-8"))


def _app_code() -> str:
    return APP_PATH.read_text(encoding="utf-8")


def _app_module():
    spec = importlib.util.spec_from_file_location("phase5_slice5c_gradio_app", APP_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_slice5c_notebook_is_clean_and_uses_project_kernel() -> None:
    notebook = _notebook()
    assert notebook["metadata"]["kernelspec"]["name"] == "enterprise-agent-poc"
    for cell in notebook["cells"]:
        if cell["cell_type"] == "code":
            assert cell.get("execution_count") is None
            assert cell.get("outputs", []) == []
    loader = "".join(notebook["cells"][1]["source"])
    assert "phase5_slice5c_gradio_app.py" in loader
    assert "importlib.util.spec_from_file_location" in loader
    assert "Path.cwd() / 'notebooks'" in loader
    assert "Path.cwd() / 'phase5_slice5c_gradio_app.py'" in loader


def test_slice5c_gradio_stays_local_and_never_manages_docker() -> None:
    code = _app_code()
    assert 'server_name="127.0.0.1"' in code
    assert "share=False" in code
    assert "inline=False" in code
    assert "inbrowser=True" in code
    assert "share=True" not in code
    assert "docker compose" not in code.lower()
    assert "subprocess" not in code.lower()
    assert "def _load_local_env" in code
    assert "_load_local_env()" in code


def test_slice5c_uses_only_token_a_in_the_ui() -> None:
    code = _app_code()
    assert "msal.PublicClientApplication" in code
    assert "initiate_device_flow" in code
    assert "acquire_token_by_device_flow" in code
    assert 'os.getenv("ENTRA_NOTEBOOK_CLIENT_ID"' in code
    assert 'os.getenv("ENTRA_AGENT_A_SCOPE"' in code
    assert "TOKEN_B_FILE" not in code
    assert "TOKEN_C_FILE" not in code
    assert "Authorization is enforced downstream" in code


def test_slice5c_chat_supports_general_read_and_transfer_prompts() -> None:
    code = _app_code()
    assert "gr.Chatbot(" in code
    assert "gr.Textbox(" in code
    assert 'submit_btn="Send"' in code
    assert "Ask Agent A anything" in code
    assert "What is the balance" in code
    assert "Transfer 25.00" in code
    assert "gr.Dropdown(" not in code
    assert "prompt.submit(" in code


def test_slice5c_transfer_requires_structured_confirmation_and_idempotency() -> None:
    code = _app_code()
    assert 'prompt == "CANCEL"' in code
    assert 'prompt != "CONFIRM"' in code
    assert "Transfer staged locally; waiting for explicit confirmation." in code
    assert "confirmation=yes" in code
    assert "idempotency_key=" in code
    assert '"idempotency_key": f"gradio-' in code
    assert "Do not change or infer any value." in code


def test_slice5c_ui_does_not_make_role_authorization_decisions() -> None:
    code = _app_code()
    assert "Banking.Reader" not in code
    assert "Banking.Writer" not in code
    assert "downstream policy decide whether the operation is allowed" in code


def test_slice5c_sign_in_can_switch_users_and_isolates_sessions() -> None:
    code = _app_code()
    assert "Sign in / switch Microsoft user" in code
    assert "hashlib.sha256" in code
    assert "session_user_state = gr.State(value=None)" in code
    assert "agent_session_state = gr.State(value=None)" in code
    assert "pending_transfer_state = gr.State(value=None)" in code
    assert "yield None, None" in code


def test_slice5c_never_displays_or_logs_tokens() -> None:
    code = _app_code().lower()
    assert "print(token_a" not in code
    assert "json.dumps(token_a" not in code
    assert "gr.textbox(value=token_a" not in code


def test_slice5c_preserves_flow_id_and_permitted_tool_boundary() -> None:
    code = _app_code()
    assert 'headers["X-Flow-ID"] = flow_id' in code
    assert '{"delegate_to_agent_b", "get_account_summary", "create_transfer"}' in code
    assert "response_flow_id != flow_id" in code
    assert "An unexpected tool appeared in the response." in code


def test_slice5c_shows_running_and_completed_activity() -> None:
    code = _app_code()
    assert 'lines = [f"✅ {step}" for step in done]' in code
    assert 'lines.append(f"⏳ {current}")' in code
    assert 'lines.append(f"❌ {error}")' in code
    assert "Agent A response received." in code
    assert "Response and tool boundary validated." in code
    assert "Request completed." in code


def test_transfer_is_staged_without_calling_agent_a(monkeypatch) -> None:
    app = _app_module()
    monkeypatch.setattr(app, "_http_json", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network called")))

    updates = list(
        app.run_agent_prompt(
            "Transfer 25.00 from acct-1001 to acct-2002.",
            [],
            "token-a",
            "entra-session-user",
            None,
            None,
        )
    )

    assert len(updates) == 1
    history, activity, cleared_prompt, session_id, pending = updates[0]
    assert history[-1]["role"] == "assistant"
    assert "Type exactly `CONFIRM`" in history[-1]["content"]
    assert "waiting for explicit confirmation" in activity
    assert cleared_prompt == ""
    assert session_id is None
    assert pending["from_account"] == "acct-1001"
    assert pending["to_account"] == "acct-2002"
    assert pending["amount"] == 25.0
    assert pending["idempotency_key"].startswith("gradio-")


def test_exact_confirm_submits_structured_transfer(monkeypatch) -> None:
    app = _app_module()
    sent_payloads = []

    def fake_http(url, *, method, token_a, payload, flow_id=None):
        sent_payloads.append((url, payload, flow_id))
        if url.endswith("/sessions"):
            return 200, {"id": "session-5c"}, {}
        return (
            200,
            [{"author": "agent_a", "content": {"parts": [{"text": "Transfer created."}]}}],
            {"X-Flow-ID": flow_id},
        )

    monkeypatch.setattr(app, "_http_json", fake_http)
    pending = {
        "from_account": "acct-1001",
        "to_account": "acct-2002",
        "amount": 25.0,
        "idempotency_key": "gradio-fixed-key",
    }
    updates = list(
        app.run_agent_prompt(
            "CONFIRM",
            [],
            "token-a",
            "entra-session-user",
            None,
            pending,
        )
    )

    assert len(updates) == 4
    run_payload = sent_payloads[-1][1]
    agent_text = run_payload["new_message"]["parts"][0]["text"]
    assert "from_account=acct-1001" in agent_text
    assert "to_account=acct-2002" in agent_text
    assert "amount=25.00" in agent_text
    assert "confirmation=yes" in agent_text
    assert "idempotency_key=gradio-fixed-key" in agent_text
    assert updates[-1][0][-1]["content"] == "Transfer created."
    assert updates[-1][-1] is None


def test_cancel_clears_pending_transfer_without_network(monkeypatch) -> None:
    app = _app_module()
    monkeypatch.setattr(app, "_http_json", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network called")))

    updates = list(
        app.run_agent_prompt(
            "CANCEL",
            [],
            "token-a",
            "entra-session-user",
            None,
            {"from_account": "acct-1001", "to_account": "acct-2002", "amount": 25.0, "idempotency_key": "key"},
        )
    )

    assert updates[0][0][-1]["content"] == "Transfer cancelled. Nothing was submitted."
    assert updates[0][-1] is None


def test_http_errors_are_user_friendly_and_do_not_expose_internals() -> None:
    module = _app_module()

    denied = module._friendly_http_error(403)
    failed = module._friendly_http_error(500)

    assert "Access denied" in denied and "HTTP 403" in denied
    assert "could not be completed" in failed and "do not own" in failed and "HTTP 500" in failed
    assert "Bearer" not in failed and "token" not in failed.lower()


def test_access_denied_result_shows_friendly_and_system_detail() -> None:
    module = _app_module()
    raw = "ACCESS_DENIED | role | Your role is not allowed to make transfers. | create_transfer is not exposed by tools/list."

    rendered = module._render_result(raw)

    assert "**Access denied.** Your role is not allowed to make transfers." in rendered
    assert "System detail (role):" in rendered and "tools/list" in rendered
    assert module._render_result("Balance is 12.00") == "Balance is 12.00"


def test_http_error_includes_system_detail_and_flow_id() -> None:
    module = _app_module()

    message = module._friendly_http_error(500, "flow-1")

    assert "System detail: HTTP 500" in message and "Flow ID: flow-1" in message
