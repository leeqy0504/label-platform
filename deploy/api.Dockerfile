FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH=/app/.venv/bin:$PATH

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY alembic.ini ./
COPY alembic ./alembic
COPY label_platform ./label_platform
COPY unitrain ./unitrain
COPY unitrain_api ./unitrain_api
COPY cli ./cli
RUN uv sync --frozen --no-dev

RUN groupadd --system platform \
    && useradd --system --gid platform --home-dir /app platform \
    && mkdir -p /data/managed \
    && chown -R platform:platform /app /data/managed

USER platform

EXPOSE 8000
CMD ["uvicorn", "label_platform.api.app:create_app_from_env", "--factory", "--host", "0.0.0.0", "--port", "8000"]
