# Extend the Docker-managed Paddle backend; retain its exact installed runtime.
ARG BASE_BACKEND=local/paper-translation-vllm-metal:latest
FROM ${BASE_BACKEND} AS existing
FROM --platform=$BUILDPLATFORM python:3.12-slim-trixie@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea AS patch
COPY --from=existing /vllm-metal /vllm-metal
COPY deployment/local-translation-backend/patch.py /patch.py
COPY deployment/local-translation-backend/translation_startup.py /vllm-metal/lib/python3.12/site-packages/translation_startup.py
COPY packages/local_models/ /catalog/
RUN python /patch.py
FROM scratch
LABEL org.opencontainers.image.title="Paper Translation Docker-managed MLX translation and Paddle backend" io.paper-translation.runtime-platform="darwin/arm64"
COPY --from=patch /vllm-metal /vllm-metal
