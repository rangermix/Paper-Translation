FROM --platform=$BUILDPLATFORM ghcr.io/astral-sh/uv:latest AS uv
FROM --platform=$BUILDPLATFORM python:3.12-slim AS build
COPY --from=uv /uv /usr/local/bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/*
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never MACOSX_DEPLOYMENT_TARGET=15.0
COPY runtime /vllm-metal
COPY requirements.in /build/requirements.in
RUN uv pip install --python-version 3.12 --python-platform aarch64-apple-darwin --target /vllm-metal/lib/python3.12/site-packages -r /build/requirements.in
RUN chmod 755 /vllm-metal/bin/python3 && printf dev > /vllm-metal/.vllm-metal-version
COPY sitecustomize.py /vllm-metal/lib/python3.12/site-packages/sitecustomize.py
FROM scratch
LABEL org.opencontainers.image.title="Paper Translation Docker-managed vLLM Metal backend" org.opencontainers.image.version="0.29.0" io.paper-translation.runtime-platform="darwin/arm64"
COPY --from=build /vllm-metal /vllm-metal
