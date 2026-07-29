# syntax=docker/dockerfile:1.7
ARG PYTHON_IMAGE=python:3.10-slim@sha256:c1e4e6c01eb489c422288b2de34b0761ca316f7a2d98e2c33f47659a73ed108a
FROM ${PYTHON_IMAGE}

ARG IRODORI_SERVER_REPOSITORY=https://github.com/Aratako/Irodori-TTS-Server.git
ARG IRODORI_SERVER_REF=1fc3e100ed8e14ff30f6bfa6cb711a948960f8ce

ENV DEBIAN_FRONTEND=noninteractive \
    HF_HOME=/runpod-volume/huggingface \
    IRODORI_CODEC_DEVICE=cuda \
    IRODORI_CODEC_PRECISION=bf16 \
    IRODORI_DEFAULT_CHUNKING_ENABLED=false \
    IRODORI_DEFAULT_NUM_STEPS=10 \
    IRODORI_MODEL_DEVICE=cuda \
    IRODORI_MODEL_PRECISION=bf16 \
    IRODORI_PRELOAD=false \
    IRODORI_VOICES_DIR=/tmp/irodori-voices \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        ffmpeg \
        git \
        libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest@sha256:606e70c71c852d03f611b1e56a195d08648507018a7057fab82c4974c4eae105 /uv /uvx /usr/local/bin/

RUN git clone "${IRODORI_SERVER_REPOSITORY}" /app/irodori-server \
    && git -C /app/irodori-server checkout --detach "${IRODORI_SERVER_REF}" \
    && test "$(git -C /app/irodori-server rev-parse HEAD)" = "${IRODORI_SERVER_REF}"

WORKDIR /app/irodori-server

RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    uv sync --locked --no-dev --no-editable --extra cu128 \
    && uv pip install "runpod==1.7.13"

COPY handler.py /app/handler.py

WORKDIR /app

CMD ["/app/.venv/bin/python", "/app/handler.py"]
