FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /workspace

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY pyproject.toml uv.lock ./
RUN uv export --locked --no-dev --format requirements-txt > /tmp/requirements.txt && \
    pip install --no-cache-dir -r /tmp/requirements.txt

COPY README.md ./README.md
COPY agents ./agents

EXPOSE 8001

HEALTHCHECK --interval=10s --timeout=5s --retries=20 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/.well-known/agent-card.json', timeout=5).read()"

CMD ["sh", "-lc", "PYTHONPATH=/workspace python -m uvicorn agents.agent_b.a2a_server:a2a_app --host 0.0.0.0 --port 8001"]
