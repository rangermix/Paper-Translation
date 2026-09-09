# syntax=docker/dockerfile:1.7
FROM ghcr.io/astral-sh/uv:0.10.7@sha256:edd1fd89f3e5b005814cc8f777610445d7b7e3ed05361f9ddfae67bebfe8456a AS uv
FROM python:3.12-slim-trixie@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea AS dependencies
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --group parser

# Model downloads depend only on their lock, not on Python dependency changes.
FROM python:3.12-slim-trixie@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea AS models
WORKDIR /app
COPY deployment/parser-models.lock.json /app/deployment/parser-models.lock.json
COPY ops/download_parser_models.py /app/ops/download_parser_models.py
RUN python /app/ops/download_parser_models.py --destination /opt/docling/models

FROM python:3.12-slim-trixie@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea AS runtime
ARG SOURCE_COMMIT=uncommitted
LABEL org.opencontainers.image.title="Offline PDF parser" org.opencontainers.image.revision=$SOURCE_COMMIT
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app HOME=/tmp \
    DOCLING_ARTIFACTS_PATH=/opt/docling/models HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
    PARSER_INPUTS=/inputs PARSER_OUTPUTS=/outputs OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 TOKENIZERS_PARALLELISM=false \
    PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True PADDLE_PDX_DISABLE_DEVICE_FALLBACK=True \
    PADDLE_PDX_LOCAL_FONT_FILE_PATH=/opt/docling/models/RapidOcr/resources/fonts/FZYTK.TTF
WORKDIR /app
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends libgomp1 libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 library && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /tmp library \
    && mkdir -p /app/release && dpkg-query -W -f='${Package}\t${Version}\n' > /app/release/system-packages.tsv
COPY --from=dependencies /app/.venv /app/.venv
RUN /usr/local/bin/python -m pip uninstall --yes pip && /usr/local/bin/python -c "import shutil; shutil.rmtree('/usr/local/lib/python3.12/ensurepip')"
COPY --from=models /opt/docling/models /opt/docling/models
COPY packages/ir/ /app/packages/ir/
COPY packages/parsers/ /app/packages/parsers/
COPY packages/metadata/discovery.py /app/packages/metadata/discovery.py
COPY packages/quality/ /app/packages/quality/
COPY packages/domain/workflow.py /app/packages/domain/workflow.py
COPY workers/parser/ /app/workers/parser/
COPY contracts/ /app/contracts/
COPY deployment/parser-models.lock.json /app/deployment/parser-models.lock.json
COPY pyproject.toml uv.lock /app/
RUN python -c "from importlib.metadata import distributions; import json; from pathlib import Path; Path('/app/release/python-packages.json').write_text(json.dumps(sorted([{'name': d.metadata['Name'], 'version': d.version, 'license': d.metadata.get('License-Expression') or d.metadata.get('License', 'UNKNOWN')} for d in distributions()], key=lambda x:x['name']), indent=2))"
ARG SOURCE_TREE_SHA256=unrecorded
LABEL dev.bilingual-library.source-tree-sha256=$SOURCE_TREE_SHA256
USER 10001:10001
CMD ["python", "-m", "workers.parser.main"]
