# =============================================================================
# Agent Platform — FastAPI Dockerfile
# Multi-stage: builder instala deps con uv, runtime ejecuta la app
# Usuario no-root, version Python fija para reproducibilidad
# =============================================================================

# ---- Stage 1: Builder -------------------------------------------------------
FROM python:3.12.8-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.11.23 /uv /uvx /bin/

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock ./

# Create the production environment without development/test dependencies.
RUN uv venv --relocatable .venv \
    && uv sync --frozen --no-install-project --no-dev

# ---- Test ------------------------------------------------------------------
# Tests run in an explicit build target and never ship in the runtime image.
FROM python:3.12.8-slim AS test

COPY --from=ghcr.io/astral-sh/uv:0.11.23 /uv /uvx /bin/

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock ./
RUN uv venv --relocatable .venv \
    && uv sync --frozen --no-install-project

ENV PATH="/app/.venv/bin:$PATH"

COPY app/ ./app/
COPY scripts/ ./scripts/
COPY tests/ ./tests/

CMD ["pytest", "-q"]

# ---- Stage 2: Runtime -------------------------------------------------------
FROM python:3.12.8-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    poppler-utils \
    tesseract-ocr \
    tesseract-ocr-spa \
    tesseract-ocr-eng \
    libgomp1 \
    libglib2.0-0 \
    libgl1 \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

# Crear usuario no-root
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser

RUN mkdir -p /data/documents/blobs /data/documents/staging \
    && chown -R appuser:appuser /data/documents

# Root owns the runtime secret directory. The entrypoint installs one 0400 copy
# for appuser before dropping every effective privilege and execing the command.
RUN install -d -o root -g appuser -m 0750 /run/agent-secrets

WORKDIR /app

# Dependencias desde builder (virtualenv relocatable creado por uv)
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Codigo fuente
COPY --chown=appuser:appuser app/ ./app/

# Infraestructura de migraciones Alembic
COPY --chown=appuser:appuser alembic-platform.ini ./
COPY --chown=appuser:appuser migrations_platform/ ./migrations_platform/

# The privileged entrypoint must not live in an appuser-writable directory:
# otherwise a compromised service could replace it before a container restart.
COPY --chown=root:root scripts/container_entrypoint.py /usr/local/libexec/agent-entrypoint.py

EXPOSE 8000

# Healthcheck a nivel Docker (complementa el del docker-compose)
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/ready || exit 1

ENTRYPOINT ["python", "/usr/local/libexec/agent-entrypoint.py"]

CMD ["uvicorn", "app.main:app", \
    "--host", "0.0.0.0", \
    "--port", "8000", \
    "--workers", "1", \
    "--no-access-log"]
