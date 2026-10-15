from __future__ import annotations

import hashlib
import html
import json
import os
import re
import uuid
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlparse

import gradio as gr
import jwt
import msal
from dotenv import load_dotenv


class DemoError(RuntimeError):
    pass


def _repo_root() -> Path:
    candidate = Path.cwd()
    if (candidate / "agents").exists():
        return candidate
    if (candidate.parent / "agents").exists():
        return candidate.parent
    raise DemoError("Open this notebook from the enterprise-agent-poc-starter workspace.")


REPO_ROOT = _repo_root()


def _load_local_env() -> None:
    """Load local configuration only when the user launches the notebook UI."""
    load_dotenv(REPO_ROOT / ".env", override=False)


def _base_url() -> str:
    value = os.getenv("SOLO_API_BASE_URL", "http://127.0.0.1:18080").strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise DemoError("The Solo API endpoint must use a loopback address.")
    return value


def _entra_settings() -> tuple[str, str, str]:
    tenant_id = os.getenv("ENTRA_TENANT_ID", "").strip()
    client_id = os.getenv("ENTRA_NOTEBOOK_CLIENT_ID", "").strip()
    scope = os.getenv("ENTRA_AGENT_A_SCOPE", "").strip()
    if not tenant_id or not client_id or not scope:
        raise DemoError("The notebook Entra configuration is incomplete.")
    return tenant_id, client_id, scope


def _device_sign_in_html(flow: object) -> str:
    if not isinstance(flow, dict):
        raise DemoError("Microsoft Entra returned an invalid device sign-in response.")
    verification_uri = flow.get("verification_uri") or flow.get("verification_url")
    user_code = flow.get("user_code")
    if not isinstance(verification_uri, str) or not isinstance(user_code, str):
        raise DemoError("Microsoft Entra did not return a device sign-in link and code.")
    parsed = urlparse(verification_uri)
    allowed_hosts = {"microsoft.com", "www.microsoft.com", "login.microsoft.com", "login.microsoftonline.com"}
    if parsed.scheme != "https" or parsed.hostname not in allowed_hosts:
        raise DemoError("Microsoft Entra returned an unapproved device sign-in link.")
    safe_uri = html.escape(verification_uri, quote=True)
    safe_code = html.escape(user_code)
    return (
        "<div style='padding:12px;border:1px solid #93c5fd;border-radius:8px'>"
        "<strong>Microsoft Entra sign-in required</strong><br><br>"
        f"<a href='{safe_uri}' target='_blank' rel='noopener noreferrer' "
        "style='display:inline-block;padding:10px 16px;background:#2563eb;color:white;text-decoration:none;border-radius:6px'>"
        "Open Microsoft sign-in</a>"
        f"<p>Enter this one-time code: <code style='font-size:1.2em'><strong>{safe_code}</strong></code></p>"
        "<p>Use the Reader or Writer test account you want to validate. This page updates when sign-in completes.</p></div>"
    )


def _identity_label(token_a: str) -> tuple[str, str]:
    try:
        claims = jwt.decode(
            token_a,
            options={"verify_signature": False, "verify_aud": False, "verify_exp": False, "verify_iss": False},
        )
    except Exception as exc:
        raise DemoError("The signed-in identity could not be read for local session isolation.") from exc
    oid = str(claims.get("oid") or "").strip()
    tid = str(claims.get("tid") or "").strip()
    username = str(claims.get("preferred_username") or "signed-in user").strip()
    if not oid or not tid:
        raise DemoError("The signed-in token did not include the required tenant and object identifiers.")
    session_user = f"entra-{hashlib.sha256(f'{tid}:{oid}'.encode()).hexdigest()[:16]}"
    return session_user, username


def sign_in_with_entra() -> Iterator[tuple[str | None, str | None, str, list[dict[str, str]], None, None]]:
    try:
        tenant_id, client_id, scope = _entra_settings()
        client = msal.PublicClientApplication(
            client_id=client_id,
            authority=f"https://login.microsoftonline.com/{tenant_id}",
        )
        flow = client.initiate_device_flow(scopes=[scope])
        yield None, None, _device_sign_in_html(flow), [], None, None
        result = client.acquire_token_by_device_flow(flow)
        token_a = result.get("access_token") if isinstance(result, dict) else None
        if not isinstance(token_a, str) or not token_a.strip():
            raise DemoError("Microsoft Entra sign-in did not complete successfully.")
        session_user, username = _identity_label(token_a)
        safe_username = html.escape(username)
        yield (
            token_a.strip(),
            session_user,
            f"<div style='color:#166534'><strong>Signed in as {safe_username}.</strong> "
            "Authorization is enforced downstream from Token C claims, not from this display name.</div>",
            [],
            None,
            None,
        )
    except DemoError as exc:
        yield None, None, f"<div style='color:#991b1b'>Sign-in failed: {html.escape(str(exc))}</div>", [], None, None
    except Exception:
        yield None, None, "<div style='color:#991b1b'>Sign-in failed unexpectedly. Check the notebook terminal.</div>", [], None, None


def _friendly_http_error(status: int, flow_id: str | None = None) -> str:
    flow = f" Flow ID: {flow_id}." if flow_id else ""
    system = f"\n\nSystem detail: HTTP {status} from the protected Agent A API.{flow} See the sanitized service logs."
    if status in {401, 403}:
        return f"Access denied (HTTP {status}). Sign in again, or use an account and action your role is allowed to use.{system}"
    if status >= 500:
        return (
            f"The request could not be completed (HTTP {status}). A common cause is asking about an account "
            "you do not own or an action your role does not allow, since the downstream service refuses it. "
            f"Try an account owned by the signed-in user.{system}"
        )
    return f"The protected API rejected the request (HTTP {status}).{system}"


_DENIAL_PATTERN = re.compile(r"ACCESS_DENIED\s*\|\s*([a-z_]+)\s*\|\s*(.+?)\s*\|\s*(.+)", re.DOTALL)


def _render_result(text: str) -> str:
    match = _DENIAL_PATTERN.search(text)
    if not match:
        return text
    category, user_message, system_message = (group.strip() for group in match.groups())
    return f"**Access denied.** {user_message}\n\n_System detail ({category}):_ {system_message}"



def _http_json(url: str, *, method: str, token_a: str, payload: object, flow_id: str | None = None):
    headers = {"Authorization": f"Bearer {token_a}", "Content-Type": "application/json"}
    if flow_id:
        headers["X-Flow-ID"] = flow_id
    req = urllib.request.Request(url, method=method, headers=headers, data=json.dumps(payload).encode("utf-8"))
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body) if body else None, dict(response.headers)
    except urllib.error.HTTPError as exc:
        raise DemoError(_friendly_http_error(exc.code, flow_id)) from exc
    except urllib.error.URLError as exc:
        raise DemoError("The local Solo API is unavailable. Start the live unified stack first.") from exc
    except json.JSONDecodeError as exc:
        raise DemoError("The protected API returned an invalid response.") from exc


def _iter_parts(events: object):
    if not isinstance(events, list):
        raise DemoError("The agent response did not match the proven contract.")
    for event in events:
        if not isinstance(event, dict):
            raise DemoError("The agent response did not match the proven contract.")
        content = event.get("content")
        parts = content.get("parts") if isinstance(content, dict) else event.get("parts")
        if parts is None:
            continue
        if not isinstance(parts, list):
            raise DemoError("The agent response did not match the proven contract.")
        yield event, parts


def _tool_payload(part: object) -> dict | None:
    if not isinstance(part, dict):
        return None
    for key in ("functionCall", "functionResponse", "function_call", "function_response", "toolCall", "toolResponse", "tool_call", "tool_response"):
        value = part.get(key)
        if isinstance(value, dict):
            return value
    return None


def _tool_name(payload: dict | None) -> str:
    if not isinstance(payload, dict):
        return ""
    return next((value for key in ("name", "tool_name", "toolName") if isinstance((value := payload.get(key)), str)), "")


def _response_text(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return next((text for item in value if (text := _response_text(item))), "")
    if isinstance(value, dict):
        return next((text for key in ("result", "output", "text", "content") if key in value and (text := _response_text(value[key]))), "")
    return ""


def _sanitize_result(text: str) -> str:
    value = re.sub(r"\b(?:acct|user)-\d+\b", "[redacted]", text.strip())
    return re.sub(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", "[redacted]", value)


def _extract_business_result(events: object) -> str:
    event_parts = list(_iter_parts(events))
    allowed_tools = {"delegate_to_agent_b", "get_account_summary", "create_transfer"}
    observed_tools = {
        _tool_name(payload).lower()
        for _, parts in event_parts
        for part in parts
        if (payload := _tool_payload(part)) is not None and _tool_name(payload)
    }
    if observed_tools - allowed_tools:
        raise DemoError("An unexpected tool appeared in the response.")
    for event, parts in reversed(event_parts):
        if str(event.get("author") or "").lower() != "agent_a":
            continue
        texts = [
            str(part["text"]).strip()
            for part in parts
            if isinstance(part, dict) and not part.get("thought") and _tool_payload(part) is None and str(part.get("text") or "").strip()
        ]
        if texts:
            return _sanitize_result("\n".join(texts))
    for _, parts in reversed(event_parts):
        for part in reversed(parts):
            payload = _tool_payload(part)
            if _tool_name(payload).lower() != "delegate_to_agent_b":
                continue
            text = _response_text(payload.get("response") if payload else None)
            if text:
                return _sanitize_result(text)
    raise DemoError("No final Agent A response was available.")


TRANSFER_PATTERN = re.compile(
    r"\btransfer\s+\$?(?P<amount>\d+(?:\.\d{1,2})?)\s+from\s+(?:synthetic\s+account\s+)?"
    r"(?P<from>acct-\d+)\s+to\s+(?:synthetic\s+account\s+)?(?P<to>acct-\d+)\b",
    re.IGNORECASE,
)


def _parse_transfer(prompt: str) -> dict[str, Any] | None:
    match = TRANSFER_PATTERN.search(prompt)
    if not match:
        return None
    amount = float(match.group("amount"))
    if amount <= 0:
        raise DemoError("Transfer amount must be greater than zero.")
    return {
        "from_account": match.group("from").lower(),
        "to_account": match.group("to").lower(),
        "amount": amount,
        "idempotency_key": f"gradio-{uuid.uuid4().hex}",
    }


def _normalize_chat(history: object) -> list[dict[str, str]]:
    if not isinstance(history, list):
        return []
    return [
        {"role": role, "content": content}
        for item in history
        if (role := (item.get("role") if isinstance(item, dict) else getattr(item, "role", None))) in {"user", "assistant"}
        and isinstance((content := (item.get("content") if isinstance(item, dict) else getattr(item, "content", None))), str)
    ]


def _activity(done: list[str], *, current: str | None = None, error: str | None = None, flow_id: str | None = None) -> str:
    lines = [f"✅ {step}" for step in done]
    if current:
        lines.append(f"⏳ {current}")
    if error:
        lines.append(f"❌ {error}")
    if flow_id:
        lines.append(f"🔎 Flow ID: {flow_id}")
    return "\n".join(lines)


def _confirmation_message(transfer: dict[str, Any]) -> str:
    return (
        f"Review transfer: **{transfer['amount']:.2f}** from **{transfer['from_account']}** "
        f"to **{transfer['to_account']}**. Type exactly `CONFIRM` to submit it or `CANCEL` to discard it. "
        "Authorization has not been decided and no transfer has been sent yet."
    )


def run_agent_prompt(
    prompt: str,
    history: object,
    token_a: str | None,
    session_user: str | None,
    session_id: str | None,
    pending_transfer: dict[str, Any] | None,
):
    chat = _normalize_chat(history)
    prompt = prompt.strip() if isinstance(prompt, str) else ""
    if not prompt:
        yield chat, "Enter a message.", prompt, session_id, pending_transfer
        return
    if len(prompt) > 800:
        yield chat, "The message is too long for this POC.", prompt, session_id, pending_transfer
        return
    if not token_a or not session_user:
        yield chat, "Sign in with Microsoft Entra first.", prompt, session_id, pending_transfer
        return

    chat.append({"role": "user", "content": prompt})
    if pending_transfer:
        if prompt == "CANCEL":
            chat.append({"role": "assistant", "content": "Transfer cancelled. Nothing was submitted."})
            yield chat, "✅ Pending transfer cancelled.", "", session_id, None
            return
        if prompt != "CONFIRM":
            chat.append({"role": "assistant", "content": "A transfer is pending. Type exactly `CONFIRM` or `CANCEL`."})
            yield chat, "⏳ Waiting for explicit transfer confirmation.", "", session_id, pending_transfer
            return
        agent_prompt = (
            "Create a banking transfer using exactly these structured values: "
            f"from_account={pending_transfer['from_account']}; "
            f"to_account={pending_transfer['to_account']}; amount={pending_transfer['amount']:.2f}; "
            f"confirmation=yes; idempotency_key={pending_transfer['idempotency_key']}. "
            "Delegate this banking operation to Agent B. Do not change or infer any value."
        )
        pending_transfer = None
    else:
        transfer = _parse_transfer(prompt)
        if transfer:
            chat.append({"role": "assistant", "content": _confirmation_message(transfer)})
            yield chat, "⏳ Transfer staged locally; waiting for explicit confirmation.", "", session_id, transfer
            return
        agent_prompt = prompt

    chat.append({"role": "assistant", "content": "Working on your request..."})
    done = ["Message validated."]
    yield chat, _activity(done, current="Creating or reusing the protected Agent A session..."), "", session_id, pending_transfer
    try:
        flow_id = f"gradio-5c-{uuid.uuid4().hex[:12]}"
        active_session = session_id.strip() if isinstance(session_id, str) else ""
        if not active_session:
            status, body, _ = _http_json(
                f"{_base_url()}/apps/agent_a/users/{session_user}/sessions",
                method="POST",
                token_a=token_a,
                payload={},
            )
            if status != 200 or not isinstance(body, dict) or not isinstance(body.get("id"), str):
                raise DemoError("The Agent A session could not be created.")
            active_session = body["id"]
            done.append("Protected Agent A session created.")
        else:
            done.append("Protected Agent A session reused.")
        yield chat, _activity(done, current="Agent A is processing the request; banking work may delegate to Agent B..."), "", active_session, pending_transfer
        status, events, headers = _http_json(
            f"{_base_url()}/run",
            method="POST",
            token_a=token_a,
            flow_id=flow_id,
            payload={
                "app_name": "agent_a",
                "user_id": session_user,
                "session_id": active_session,
                "new_message": {"role": "user", "parts": [{"text": agent_prompt}]},
            },
        )
        if status != 200:
            raise DemoError("Agent A did not complete the request.")
        response_flow_id = next((value for key, value in headers.items() if key.lower() == "x-flow-id"), None)
        if response_flow_id != flow_id:
            raise DemoError("The protected API did not preserve the flow identifier.")
        done.append("Agent A response received.")
        yield chat, _activity(done, current="Validating the response and permitted tool boundary..."), "", active_session, pending_transfer
        result = _render_result(_extract_business_result(events))
        done.extend(["Response and tool boundary validated.", "Request completed."])
        chat[-1] = {"role": "assistant", "content": result}
        yield chat, _activity(done, flow_id=flow_id), "", active_session, pending_transfer
    except DemoError as exc:
        chat[-1] = {"role": "assistant", "content": f"Request failed: {exc}"}
        yield chat, _activity(done, error=str(exc)), prompt, session_id, pending_transfer
    except Exception:
        message = "Request failed unexpectedly. Check the sanitized service logs."
        chat[-1] = {"role": "assistant", "content": message}
        yield chat, _activity(done, error=message), prompt, session_id, pending_transfer


def build_demo() -> gr.Blocks:
    with gr.Blocks(title="Enterprise Agent POC — Slice 5C") as demo:
        gr.Markdown(
            "# Enterprise Agent POC — Per-user banking authorization\n"
            "Sign in as either the Reader or Writer test user. Ask general questions, read account data, or type a transfer request. "
            "Transfers are staged until you type exactly `CONFIRM`; Entra roles and downstream policy decide whether the operation is allowed."
        )
        token_a_state = gr.State(value=None)
        session_user_state = gr.State(value=None)
        agent_session_state = gr.State(value=None)
        pending_transfer_state = gr.State(value=None)
        sign_in = gr.Button("Sign in / switch Microsoft user", variant="primary")
        sign_in_status = gr.HTML("<p>Select <strong>Sign in / switch Microsoft user</strong> to begin.</p>")
        chat = gr.Chatbot(label="Conversation with Agent A", layout="bubble", height=None, min_height=100, max_height=240, buttons=["copy"])
        prompt = gr.Textbox(
            label="Message",
            placeholder="Ask Agent A anything.",
            lines=2,
            max_lines=6,
            info="Enter adds a new line. Select Send to submit. Type CONFIRM or CANCEL when a transfer is pending.",
            submit_btn="Send",
        )
        gr.Textbox(
            label="Sample read",
            value="What is the balance for synthetic account acct-1001?",
            interactive=False,
            lines=1,
            buttons=["copy"],
        )
        gr.Textbox(
            label="Sample transfer",
            value="Transfer 25.00 from acct-1001 to acct-2002.",
            interactive=False,
            lines=1,
            buttons=["copy"],
        )
        activity = gr.Textbox(label="Live request activity", interactive=False, lines=4, max_lines=8)
        gr.Markdown(
            "The UI does not grant permissions. Reader/Writer authorization, account ownership, confirmation, amount validation, "
            "and idempotency are enforced at the Token C, gateway, Agent B client, and Banking MCP boundaries."
        )
        sign_in.click(
            fn=sign_in_with_entra,
            inputs=None,
            outputs=[token_a_state, session_user_state, sign_in_status, chat, agent_session_state, pending_transfer_state],
        )
        prompt.submit(
            fn=run_agent_prompt,
            inputs=[prompt, chat, token_a_state, session_user_state, agent_session_state, pending_transfer_state],
            outputs=[chat, activity, prompt, agent_session_state, pending_transfer_state],
        )
    return demo


def launch_demo() -> gr.Blocks:
    _load_local_env()
    demo = build_demo()
    demo.queue(default_concurrency_limit=1)
    demo.launch(
        inline=False,
        inbrowser=True,
        share=False,
        server_name="127.0.0.1",
        prevent_thread_lock=True,
        show_error=False,
    )
    return demo


__all__ = ["DemoError", "build_demo", "launch_demo", "run_agent_prompt", "sign_in_with_entra"]
