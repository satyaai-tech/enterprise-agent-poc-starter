from __future__ import annotations

import re
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import Response

from google.adk.cli.fast_api import get_fast_api_app

from agents.flow_logging import get_flow_id, reset_flow_id, set_flow_id

_FLOW_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def _normalize_flow_id(value: str | None) -> str:
    if value is None:
        return uuid.uuid4().hex[:12]
    candidate = value.strip()
    if not candidate or len(candidate) > 128 or _FLOW_ID_PATTERN.fullmatch(candidate) is None:
        return uuid.uuid4().hex[:12]
    return candidate


def _wrap_with_flow_id_middleware(app: FastAPI) -> FastAPI:
    @app.middleware("http")
    async def _flow_id_middleware(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        incoming = request.headers.get("x-flow-id")
        effective_flow_id = _normalize_flow_id(incoming)
        token = set_flow_id(effective_flow_id)
        try:
            response = await call_next(request)
            response.headers["X-Flow-ID"] = effective_flow_id
            return response
        finally:
            reset_flow_id(token)

    return app


def build_agent_a_http_app() -> FastAPI:
    app = get_fast_api_app(
        agents_dir="/workspace/agents/agent_a",
        web=True,
        a2a=False,
        host="0.0.0.0",
        port=8000,
    )
    return _wrap_with_flow_id_middleware(app)


app = build_agent_a_http_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
