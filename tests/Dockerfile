# Development tests and repository checks; no parser models or provider credentials.
FROM node:22-trixie-slim@sha256:7b8a0c89c54499bee567618f96578e1a12a800f062fbdbfd1fb6a443fa6f6284 AS frontend
WORKDIR /web
COPY src/apps/web/package.json src/apps/web/package-lock.json ./
RUN npm ci --ignore-scripts
COPY src/apps/web/ ./
RUN npm run build

FROM ghcr.io/astral-sh/uv:0.10.7@sha256:edd1fd89f3e5b005814cc8f777610445d7b7e3ed05361f9ddfae67bebfe8456a AS uv
FROM python:3.12-slim-trixie@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/src PATH=/app/.venv/bin:$PATH
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen
COPY . /app
COPY --from=frontend /web/dist/ /app/src/apps/web/dist/
RUN mkdir -p /app/.agent/tmp /app/.agent/harness && chown -R 10001:10001 /app/.agent
USER 10001:10001
CMD ["python", "-m", "pytest", "-q", "-rs"]
