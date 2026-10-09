FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY phase0_validation ./phase0_validation
COPY infra/kong/spikes/external-authorizer/proxy/app.py ./infra/kong/spikes/external-authorizer/proxy/app.py

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

CMD ["uv", "run", "python", "infra/kong/spikes/external-authorizer/proxy/app.py"]