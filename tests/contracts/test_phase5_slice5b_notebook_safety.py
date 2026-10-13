from __future__ import annotations

import json
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
NOTEBOOK_PATH = REPO_ROOT / "notebooks" / "phase-5-slice-5b-read-only-demo.ipynb"


def _load_notebook() -> dict:
    return json.loads(NOTEBOOK_PATH.read_text(encoding="utf-8"))


def _code_cells(notebook: dict) -> list[dict]:
    return [cell for cell in notebook.get("cells", []) if cell.get("cell_type") == "code"]


def _code_text(notebook: dict) -> str:
    chunks: list[str] = []
    for cell in _code_cells(notebook):
        chunks.append("".join(cell.get("source", [])))
    return "\n".join(chunks)


def test_notebook_outputs_are_cleared_and_execution_counts_are_empty() -> None:
    notebook = _load_notebook()
    for cell in _code_cells(notebook):
        assert cell.get("outputs", []) == []
        assert cell.get("execution_count") is None


def test_executable_cells_do_not_access_downstream_tokens_or_jwt_decoding() -> None:
    code = _code_text(_load_notebook())
    prohibited_fragments = [
        "TOKEN_B_FILE",
        "TOKEN_C_FILE",
        "import jwt",
        "jwt.",
    ]
    for fragment in prohibited_fragments:
        assert fragment not in code
    assert re.search(r"\btoken_[bc]\b", code, flags=re.IGNORECASE) is None


def test_notebook_obtains_only_token_a_with_device_code() -> None:
    code = _code_text(_load_notebook())
    assert "msal.PublicClientApplication" in code
    assert "initiate_device_flow" in code
    assert "acquire_token_by_device_flow" in code
    assert 'os.getenv("ENTRA_NOTEBOOK_CLIENT_ID"' in code
    assert 'os.getenv("ENTRA_AGENT_A_SCOPE"' in code
    assert "TOKEN_A_FILE" not in code


def test_executable_cells_do_not_slice_or_print_tokens_or_authorization_headers() -> None:
    code = _code_text(_load_notebook())
    assert re.search(r"token[^\n]{0,24}\[:\d+", code, flags=re.IGNORECASE) is None
    assert "print(TOKEN_A" not in code
    assert re.search(r"print\([^\n]*Authorization", code, flags=re.IGNORECASE) is None
    assert re.search(r"json\.dumps\([^\n]*(RUN_EVENTS|headers)", code) is None


def test_executable_cells_do_not_manage_docker_or_process_lifecycle() -> None:
    code = _code_text(_load_notebook()).lower()
    prohibited_fragments = [
        "docker",
        "docker compose",
        "subprocess",
        "popen(",
        "system(",
    ]
    for fragment in prohibited_fragments:
        assert fragment not in code


def test_notebook_restricts_api_access_to_loopback() -> None:
    code = _code_text(_load_notebook())
    assert 'os.getenv("SOLO_API_BASE_URL", "http://127.0.0.1:18080")' in code
    assert '{"127.0.0.1", "localhost", "::1"}' in code
    disallowed_literals = [
        "http://host.docker.internal",
        "http://0.0.0.0",
    ]
    for literal in disallowed_literals:
        assert literal not in code


def test_notebook_uses_the_proven_session_contract() -> None:
    code = _code_text(_load_notebook())
    assert 'f"{SOLO_API_BASE_URL}/apps/{APP_NAME}/users/{USER_ID}/sessions"' in code
    assert "payload={}" in code
    assert '"Authorization": f"Bearer {TOKEN_A}"' in code


def test_notebook_uses_the_proven_run_contract_and_flow_id() -> None:
    code = _code_text(_load_notebook())
    required_fragments = [
        'f"{SOLO_API_BASE_URL}/run"',
        '"app_name": APP_NAME',
        '"user_id": USER_ID',
        '"session_id": SESSION_ID',
        '"new_message": {',
        '"role": "user"',
        '"parts": [{"text": PROMPT_TEXT}]',
        '"X-Flow-ID": FLOW_ID',
    ]
    for fragment in required_fragments:
        assert fragment in code


def test_notebook_prompt_and_expected_tool_are_read_only() -> None:
    code = _code_text(_load_notebook())
    prompt_match = re.search(r'PROMPT_TEXT = \(\n\s+"([^"]+)"', code)
    assert prompt_match is not None
    prompt = prompt_match.group(1).lower()
    assert "balance" in prompt
    assert "read-only" in prompt
    assert "delegate" not in prompt
    assert "agent b" not in prompt
    assert "get_account_summary" not in prompt
    prohibited_prompt_terms = [
        "create_transfer",
        "transfer funds",
        "transfer money",
        "write confirmation",
        "idempotency",
    ]
    for term in prohibited_prompt_terms:
        assert term not in prompt
    prohibited_code_terms = [
        "create_transfer",
        "transfer_mutation",
        "write_confirmation",
        "idempotency_key",
    ]
    for term in prohibited_code_terms:
        assert term not in code


def test_notebook_does_not_dump_raw_event_payloads() -> None:
    code = _code_text(_load_notebook())
    prohibited_patterns = [
        r"print\(RUN_EVENTS\)",
        r"print\(json\.dumps\(RUN_EVENTS",
        r"pprint\(RUN_EVENTS\)",
    ]
    for pattern in prohibited_patterns:
        assert re.search(pattern, code) is None


def test_notebook_accepts_only_the_proven_delegation_response_as_final_text_fallback() -> None:
    code = _code_text(_load_notebook())
    assert "def _extract_delegate_to_agent_b_response" in code
    assert '_tool_name(payload) != "delegate_to_agent_b"' in code
    assert 'payload.get("response")' in code
    assert "FINAL_RESULT = _extract_delegate_to_agent_b_response(RUN_EVENTS)" in code


def test_notebook_requires_client_visible_delegation_but_not_agent_b_internal_mcp_events() -> None:
    code = _code_text(_load_notebook())
    assert 'if not SUMMARY["delegated_to_agent_b"] or not SUMMARY["a2a_response_received"]' in code
    assert 'not SUMMARY["mcp_tool_call_started"]' not in code
    assert 'not SUMMARY["mcp_tool_call_completed"]' not in code
    assert '"mcp_lifecycle_visibility"' in code
