FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml ./
RUN uv sync --no-dev

COPY . .

ENV PYTHONPATH=/app/src
CMD ["uv", "run", "--no-sync", "python", "-m", "worker.entrypoints.worker"]
