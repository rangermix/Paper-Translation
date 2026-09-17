# syntax=docker/dockerfile:1.7
FROM node:22-trixie-slim@sha256:7b8a0c89c54499bee567618f96578e1a12a800f062fbdbfd1fb6a443fa6f6284 AS frontend
WORKDIR /web
COPY src/apps/web/package.json src/apps/web/package-lock.json ./
RUN npm ci --ignore-scripts
COPY src/apps/web/ ./
RUN npm run build

FROM ghcr.io/astral-sh/uv:0.10.7@sha256:edd1fd89f3e5b005814cc8f777610445d7b7e3ed05361f9ddfae67bebfe8456a AS uv
FROM python:3.12-slim-trixie@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea AS dependencies
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

FROM postgres:15-trixie@sha256:9b1d34adbce1dd07ee6e94b4a2cf698884b89bd44a6c9c12f5da8f3acbfe4957 AS postgres_client
FROM python:3.12-slim-trixie@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea AS runtime
ARG SOURCE_COMMIT=uncommitted
LABEL org.opencontainers.image.title="Bilingual personal PDF library" org.opencontainers.image.revision=$SOURCE_COMMIT
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app/src HOME=/tmp
WORKDIR /app
# PostgreSQL 15 server and client share a major version. Exact dpkg versions are
# included in the built image inventory and release evidence.
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends libpq5 liblz4-1 libzstd1 libreadline8t64 ca-certificates && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 library && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /tmp library \
    && mkdir -p /app/release && dpkg-query -W -f='${Package}\t${Version}\n' > /app/release/system-packages.tsv
COPY --from=dependencies /app/.venv /app/.venv
RUN /usr/local/bin/python -m pip uninstall --yes pip && /usr/local/bin/python -c "import shutil; shutil.rmtree('/usr/local/lib/python3.12/ensurepip')"
COPY --from=postgres_client /usr/lib/postgresql/15/bin/pg_dump /usr/local/bin/pg_dump
COPY --from=postgres_client /usr/lib/postgresql/15/bin/pg_restore /usr/local/bin/pg_restore
COPY --from=postgres_client /usr/lib/postgresql/15/bin/psql /usr/local/bin/psql
RUN pg_dump --version && pg_restore --version && psql --version
COPY src/apps/api/ /app/src/apps/api/
COPY src/packages/ /app/src/packages/
COPY src/workers/ /app/src/workers/
COPY res/schemas/ /app/res/schemas/
COPY deployment/parser-models.lock.json /app/deployment/parser-models.lock.json
COPY res/reference/ /app/res/reference/
COPY pyproject.toml uv.lock /app/
COPY --from=frontend /web/dist/ /app/src/apps/web/dist/
RUN python -c "from importlib.metadata import distributions; import json; from pathlib import Path; Path('/app/release/python-packages.json').write_text(json.dumps(sorted([{'name': d.metadata['Name'], 'version': d.version, 'license': d.metadata.get('License-Expression') or d.metadata.get('License', 'UNKNOWN')} for d in distributions()], key=lambda x:x['name']), indent=2))"
RUN python -c "from packages.parsers.models import parser_version; print(parser_version())"
ARG SOURCE_TREE_SHA256=unrecorded
LABEL dev.bilingual-library.source-tree-sha256=$SOURCE_TREE_SHA256
USER 10001:10001
CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8080"]
