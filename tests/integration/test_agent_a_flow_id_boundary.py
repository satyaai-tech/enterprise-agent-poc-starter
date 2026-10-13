from __future__ import annotations

import asyncio
import re

import httpx
import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from agents.agent_a.a2a_client import _public_a2a_headers
from agents.agent_a.http_app import _wrap_with_flow_id_middleware
from agents.flow_logging import get_flow_id, reset_flow_id, set_flow_id


def _asgi_call(app, *, headers=None, path="/", method="GET"):
    client = TestClient(app)
    return client.request(method, path, headers=headers or {})


def _wrapped_demo_app() -> FastAPI:
    app = FastAPI()

    @app.get("/echo-flow")
    def echo_flow() -> dict[str, str]:
        return {"flow_id": get_flow_id()}

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("boom")

    @app.get("/a2a-headers")
    def a2a_headers() -> dict[str, object]:
        return {
            "context_flow_id": get_flow_id(),
            "downstream_headers": _public_a2a_headers(),
        }

    return _wrap_with_flow_id_middleware(app)


def test_valid_incoming_flow_id_is_accepted():
    from agents.agent_a.http_app import app

    response = _asgi_call(app, headers={"X-Flow-ID": "req-123"}, path="/")
    assert response.status_code in {200, 404}
    assert response.headers.get("X-Flow-ID") == "req-123"


def test_missing_flow_id_generates_one():
    from agents.agent_a.http_app import app

    response = _asgi_call(app, path="/")
    assert response.status_code in {200, 404}
    assert response.headers.get("X-Flow-ID")
    assert re.fullmatch(r"[A-Za-z0-9._:-]+", response.headers["X-Flow-ID"]) is not None


def test_invalid_or_oversized_flow_id_is_replaced():
    from agents.agent_a.http_app import app

    oversized = "x" * 512
    response = _asgi_call(app, headers={"X-Flow-ID": "not valid!"}, path="/")
    assert response.status_code in {200, 404}
    assert response.headers.get("X-Flow-ID") != "not valid!"

    response2 = _asgi_call(app, headers={"X-Flow-ID": oversized}, path="/")
    assert response2.status_code in {200, 404}
    assert response2.headers.get("X-Flow-ID") != oversized


def test_response_returns_effective_flow_id():
    from agents.agent_a.http_app import app

    response = _asgi_call(app, headers={"X-Flow-ID": "flow-abc"}, path="/")
    assert response.headers.get("X-Flow-ID") == "flow-abc"


async def _fetch_flow(app: FastAPI, flow_id: str) -> tuple[dict[str, str], str, int]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/echo-flow", headers={"X-Flow-ID": flow_id})
        return response.json(), response.headers.get("X-Flow-ID", ""), response.status_code


def test_concurrent_requests_do_not_leak_flow_ids():
    app = _wrapped_demo_app()
    values = ["flow-a", "flow-b", "flow-c"]

    async def _run():
        return await asyncio.gather(*(_fetch_flow(app, value) for value in values))

    results = asyncio.run(_run())

    for (payload, header, status_code), expected in zip(results, values):
        assert status_code == 200
        assert payload["flow_id"] == expected
        assert header == expected

    observed = [result[0]["flow_id"] for result in results]
    assert observed == values


def test_contextvar_reset_after_success_and_failure():
    app = _wrapped_demo_app()
    outer_token = set_flow_id("outer-flow")
    try:
        response = _asgi_call(app, headers={"X-Flow-ID": "after"}, path="/echo-flow")
        assert response.status_code == 200
        assert response.json()["flow_id"] == "after"
        assert get_flow_id() == "outer-flow"
    finally:
        reset_flow_id(outer_token)

    outer_token = set_flow_id("outer-before-failure")
    try:
        with pytest.raises(RuntimeError, match="boom"):
            _asgi_call(app, headers={"X-Flow-ID": "failed-request-flow"}, path="/boom")
        assert get_flow_id() == "outer-before-failure"
    finally:
        reset_flow_id(outer_token)


def test_downstream_a2a_request_receives_same_flow_id():
    app = _wrapped_demo_app()

    response = _asgi_call(app, headers={"X-Flow-ID": "a2a-flow"}, path="/a2a-headers")
    assert response.status_code == 200
    assert response.json()["context_flow_id"] == "a2a-flow"
    assert response.json()["downstream_headers"] == {"X-Flow-ID": "a2a-flow"}


def test_invalid_or_oversized_header_is_replaced_not_reflected():
    from agents.agent_a.http_app import app

    bad = "bad!value"
    response = _asgi_call(app, headers={"X-Flow-ID": bad}, path="/")
    assert response.status_code in {200, 404}
    assert response.headers.get("X-Flow-ID") != bad
