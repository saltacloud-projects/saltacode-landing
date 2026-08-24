# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:0.11.23 AS uv

FROM python:3.12-slim AS builder
COPY --from=uv /uv /uvx /bin/
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim AS runtime
RUN groupadd --gid 10001 agent \
    && useradd --uid 10001 --gid agent --home-dir /app --no-create-home \
      --shell /usr/sbin/nologin agent

WORKDIR /app
COPY --from=builder --chown=agent:agent /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER agent
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/health/live', timeout=2)"]

CMD ["uvicorn", "saltacode_agent.transport.http.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8001", "--no-access-log"]
