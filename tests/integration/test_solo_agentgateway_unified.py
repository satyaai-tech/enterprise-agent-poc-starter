from __future__ import annotations

import importlib.util
import os
import socket
import subprocess
import time
import urllib.request
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PROFILE_DIR = REPO_ROOT / "experiments" / "solo-agentgateway" / "unified"
COMPOSE_FILE = PROFILE_DIR / "compose.yaml"
RENDERER_PATH = PROFILE_DIR / "render_config.py"


def _load_renderer():
    spec = importlib.util.spec_from_file_location("unified_render_config", RENDERER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _compose(env: dict[str, str], *args: str, check: bool = True):
    return subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), *args],
        cwd=REPO_ROOT,
        env=env,
        check=check,
        capture_output=True,
        text=True,
    )


def _wait(url: str, timeout: float = 90.0) -> bytes:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                return response.read()
        except Exception as exc:  # pragma: no cover - diagnostics retained by timeout
            last_error = exc
            time.sleep(1)
    raise RuntimeError(f"Timed out waiting for {url}: {last_error}")


def test_unified_config_has_three_listeners_and_private_backends(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    monkeypatch.setenv("AG_CONFIG_PATH", str(config_dir))
    config_path = Path(_load_renderer().render())
    rendered = config_path.read_text(encoding="utf-8")

    assert "api-edge:\n    port: 8080" in rendered
    assert "a2a:\n    port: 8081" in rendered
    assert "mcp:\n    port: 8082" in rendered
    assert 'host: "agent-a:8000"' in rendered
    assert 'host: "agent-b:8001"' in rendered
    assert 'host: "http://banking-mcp:8080/mcp"' in rendered
    assert "gateways: [api-edge]" in rendered
    assert "gateways: [a2a]" in rendered
    assert "gateways: [mcp]" in rendered


def test_unified_compose_publishes_only_gateway_ports(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    monkeypatch.setenv("AG_CONFIG_PATH", str(config_dir))
    _load_renderer().render()
    env = os.environ.copy()
    env.update(
        {
            "AG_CONFIG_PATH": str(config_dir),
            "API_HOST_PORT": str(_free_port()),
            "A2A_HOST_PORT": str(_free_port()),
            "MCP_HOST_PORT": str(_free_port()),
        }
    )
    result = _compose(env, "config")
    assert result.returncode == 0
    assert "agentgateway:" in result.stdout
    assert "agent-a:" in result.stdout
    assert "agent-b:" in result.stdout
    assert "banking-mcp:" in result.stdout
    assert result.stdout.count("published:") == 3


def test_unified_gateway_routes_all_three_listeners(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    monkeypatch.setenv("AG_CONFIG_PATH", str(config_dir))
    _load_renderer().render()
    api_port, a2a_port, mcp_port = _free_port(), _free_port(), _free_port()
    env = os.environ.copy()
    env.update(
        {
            "COMPOSE_PROJECT_NAME": f"solo-unified-{uuid.uuid4().hex[:8]}",
            "AG_CONFIG_PATH": str(config_dir),
            "API_HOST_PORT": str(api_port),
            "A2A_HOST_PORT": str(a2a_port),
            "MCP_HOST_PORT": str(mcp_port),
        }
    )
    try:
        _compose(env, "up", "-d", "--build", "--wait")
        assert b"ok" in _wait(f"http://127.0.0.1:{api_port}/health").lower()
        assert b"agent_b" in _wait(
            f"http://127.0.0.1:{a2a_port}/.well-known/agent-card.json"
        ).lower()
        assert b"mock-banking" in _wait(
            f"http://127.0.0.1:{mcp_port}/healthz"
        ).lower()
    finally:
        _compose(env, "down", "-v", "--remove-orphans", check=False)
