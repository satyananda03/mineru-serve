FROM python:3.13-slim-bookworm AS base

RUN apt-get update \
    && apt-get install -y --no-install-recommends libmagic1 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11.2 /uv /bin/uv

RUN useradd --create-home --uid 1000 app && mkdir /app && chown app:app /app
USER app
WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_HTTP_TIMEOUT=300 \
    PATH="/app/.venv/bin:$PATH"

COPY --chown=app:app pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/home/app/.cache/uv,uid=1000,gid=1000 \
    uv sync --frozen --no-dev --no-install-project

FROM base AS app

ENV DO_NOT_TRACK=true \
    SCARF_NO_ANALYTICS=true \
    UNSTRUCTURED_DISABLE_NOTICE=1

COPY --chown=app:app src ./src
COPY --chown=app:app run.py ./

EXPOSE 8000
CMD ["python", "run.py"]

FROM base AS mineru

ARG BACKEND=torch
ENV MINERU_MODEL_SMALL_BACKEND=${BACKEND} \
    HF_HOME=/app/.cache/huggingface

RUN --mount=type=cache,target=/home/app/.cache/uv,uid=1000,gid=1000 \
    if [ "$BACKEND" = torch ]; then uv sync --frozen --no-dev --no-install-project --extra gpu; fi

RUN mineru-kit models download --tier basic --small-backend "$BACKEND" --source huggingface

ENV HF_HUB_OFFLINE=1 \
    MINERU_MODEL_SOURCE=local
RUN mineru-kit models verify --tier basic --small-backend "$BACKEND"

COPY --chown=app:app src/core/logging.py ./src/core/logging.py
COPY --chown=app:app src/models ./src/models

EXPOSE 8000
ENTRYPOINT ["python", "-m", "src.models", "--host", "0.0.0.0", "--port", "8000", "--tier", "basic", "--preload-models"]
