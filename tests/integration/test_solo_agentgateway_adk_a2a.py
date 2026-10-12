from __future__ import annotations

import asyncio
import importlib.util
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from a2a.client import A2ACardResolver, ClientConfig, create_client
from a2a.types.a2a_pb2 import Message, Part, Role, SendMessageRequest


MODULE_PATH = Path(__file__).resolve().parents[2] / "experiments" / "solo-agentgateway" / "adk-a2a" / "render_config.py"
SPEC = importlib.util.spec_from_file_location("solo_adk_a2a_render_config", MODULE_PATH)
assert SPEC and SPEC.loader
render_config = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(render_config)

import agents.agent_b.a2a_server as a2a_server


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _is_adk_thought(value):
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


def _extract_first_text(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
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
            text = getattr(part, "text", "")
            if text and not getattr(part, "thought", False):
                return text.strip()
    if hasattr(value, "task"):
        return _extract_first_text(getattr(value, "task"))
    if hasattr(value, "message"):
        return _extract_first_text(getattr(value, "message"))
    return ""


def _extract_public_card_url(card):
    if isinstance(card, dict):
        if card.get("url"):
            return card["url"]
        for key in ("supportedInterfaces", "supported_interfaces"):
            interfaces = card.get(key, [])
            if isinstance(interfaces, list):
                for interface in interfaces:
                    if isinstance(interface, dict) and interface.get("url"):
                        return interface["url"]
    if hasattr(card, "supported_interfaces"):
        for interface in getattr(card, "supported_interfaces", []):
            if getattr(interface, "url", None):
                return interface.url
    return None


def test_render_config_routes_public_card_and_private_backend(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config_dir = tmp_path / "agentgateway-config-dir"
    monkeypatch.setenv("AG_CONFIG_PATH", str(config_dir))
    monkeypatch.setenv("A2A_PUBLIC_URL", "http://127.0.0.1:18081")

    rendered = render_config.render()
    config_path = config_dir / "config.yaml"
    config_text = config_path.read_text(encoding="utf-8")

    assert rendered == str(config_path)
    assert "agent-b:8001" in config_text
    assert "/.well-known/agent-card.json" in config_text
    assert "pathPrefix: /" in config_text
    assert "jwt" not in config_text.lower()


def test_render_config_uses_directory_path_for_gateway_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config_dir = tmp_path / "agentgateway-config-dir"
    config_dir.mkdir()
    monkeypatch.setenv("AG_CONFIG_PATH", str(config_dir))
    monkeypatch.setenv("A2A_PUBLIC_URL", "http://127.0.0.1:18081")

    rendered = render_config.render()
    expected_path = config_dir / "config.yaml"

    assert rendered == str(expected_path)
    assert expected_path.exists()
    assert "agent-b:8001" in expected_path.read_text(encoding="utf-8")


def test_agent_b_server_advertises_gateway_public_url() -> None:
    original_host = a2a_server.A2A_HOST
    original_port = a2a_server.A2A_PORT
    original_public_url = a2a_server.A2A_PUBLIC_URL
    original_agent = a2a_server.build_agent_b

    try:
        a2a_server.A2A_HOST = "0.0.0.0"
        a2a_server.A2A_PORT = 8001
        a2a_server.A2A_PUBLIC_URL = "http://127.0.0.1:18081"
        fake_agent = object()
        fake_interface = type("FakeInterface", (), {"url": "http://127.0.0.1:18081/"})()
        fake_card = type("FakeCard", (), {"supported_interfaces": [fake_interface]})()

        with patch("agents.agent_b.a2a_server.build_agent_b", return_value=fake_agent), patch(
            "agents.agent_b.a2a_server._build_public_agent_card", return_value=fake_card
        ), patch("agents.agent_b.a2a_server.to_a2a", return_value="a2a-app") as to_a2a_mock:
            app = a2a_server.create_a2a_app()

        assert app == "a2a-app"
        card = to_a2a_mock.call_args.kwargs["agent_card"]
        assert card is not None
        assert card.supported_interfaces[0].url == "http://127.0.0.1:18081/"
    finally:
        a2a_server.A2A_HOST = original_host
        a2a_server.A2A_PORT = original_port
        a2a_server.A2A_PUBLIC_URL = original_public_url
        a2a_server.build_agent_b = original_agent


def test_compose_binds_only_gateway_host_port() -> None:
    compose_path = Path(__file__).resolve().parents[2] / "experiments" / "solo-agentgateway" / "adk-a2a" / "compose.yaml"
    compose_text = compose_path.read_text(encoding="utf-8")

    assert '127.0.0.1:${HOST_PORT:-18081}:8080' in compose_text
    assert 'A2A_PUBLIC_URL: http://127.0.0.1:${HOST_PORT:-18081}' in compose_text
    assert 'A2A_HOST: 0.0.0.0' in compose_text
    assert '"8001"' in compose_text
    assert '"127.0.0.1:8001:8001"' not in compose_text


def test_solo_agentgateway_adk_a2a_runtime_proof(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    compose_path = repo_root / "experiments" / "solo-agentgateway" / "adk-a2a" / "compose.yaml"
    config_dir = tmp_path / "agentgateway-config"
    host_port = _find_free_port()
    env = os.environ.copy()
    env["HOST_PORT"] = str(host_port)
    env["AG_CONFIG_PATH"] = str(config_dir)
    env["COMPOSE_PROJECT_NAME"] = f"solo-adk-a2a-{host_port}"

    try:
        subprocess.run([sys.executable, str(MODULE_PATH)], check=True, env=env, capture_output=True, text=True)
        subprocess.run(
            ["docker", "compose", "-f", str(compose_path), "up", "-d", "--wait"],
            cwd=str(repo_root),
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )

        gateway_url = f"http://127.0.0.1:{host_port}"
        deadline = time.time() + 90
        last_error = None
        while time.time() < deadline:
            try:
                response = httpx.get(f"{gateway_url}/.well-known/agent-card.json", timeout=5)
                response.raise_for_status()
                card = response.json()
                public_url = _extract_public_card_url(card)
                assert public_url == f"{gateway_url}/"
                break
            except Exception as exc:  # pragma: no cover - retry loop for readiness
                last_error = exc
                time.sleep(2)
        else:
            raise AssertionError(f"Solo gateway did not become ready: {last_error}")

        port_result = subprocess.run(
            ["docker", "compose", "-f", str(compose_path), "port", "agent-b", "8001"],
            cwd=str(repo_root),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        port_output = port_result.stdout.strip()
        assert port_result.returncode == 0 and (port_output == "" or port_output.startswith("invalid IP:0"))

        async def send_message() -> str:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resolver = A2ACardResolver(client, gateway_url)
                card = await resolver.get_agent_card()
                assert card is not None
                client_config = ClientConfig(streaming=False, httpx_client=client)
                remote_client = await create_client(gateway_url, client_config=client_config)
                try:
                    request = SendMessageRequest(
                        message=Message(
                            message_id="solo-adk-a2a-proof",
                            role=Role.ROLE_USER,
                            parts=[Part(text="Reply with PASS and nothing else")],
                        )
                    )
                    async for event in remote_client.send_message(request):
                        extracted = _extract_first_text(event)
                        if extracted:
                            return extracted
                    raise AssertionError("No A2A response text received through Solo")
                finally:
                    await remote_client.close()

        response_text = asyncio.run(send_message())
        assert response_text.strip()
        assert response_text.upper() == "PASS"
    finally:
        subprocess.run(
            ["docker", "compose", "-f", str(compose_path), "down", "-v", "--remove-orphans"],
            cwd=str(repo_root),
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
