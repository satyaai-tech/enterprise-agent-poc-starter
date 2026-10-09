FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY infra/kong/spikes/external-authorizer/agent-a-mock/app.py ./infra/kong/spikes/external-authorizer/agent-a-mock/app.py

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

CMD ["uv", "run", "python", "infra/kong/spikes/external-authorizer/agent-a-mock/app.py"]