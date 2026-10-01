# syntax=docker/dockerfile:1.7
ARG PARSER_FLAVOR=cpu
FROM ghcr.io/astral-sh/uv:0.10.7@sha256:edd1fd89f3e5b005814cc8f777610445d7b7e3ed05361f9ddfae67bebfe8456a AS uv
FROM python:3.12-slim-trixie@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea AS dependencies-cpu
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --group parser && mkdir -p /app/.venv-paddle
COPY deployment/teleocr/pyproject.toml deployment/teleocr/uv.lock /tele/
# TeleOCR's pinned custom code uses Transformers 4.57. Share Torch and the base
# parser packages through a .pth file; do not duplicate native inference wheels.
RUN UV_PROJECT_ENVIRONMENT=/app/.venv-tele uv sync --project /tele --frozen --no-dev \
    && echo /app/.venv/lib/python3.12/site-packages > /app/.venv-tele/lib/python3.12/site-packages/parser-native.pth

# One unified CUDA image, two isolated Python environments: PyTorch and
# Paddle require incompatible pinned cuDNN/NCCL packages.
FROM python:3.12-slim-trixie@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea AS dependencies-cuda
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
WORKDIR /app
COPY deployment/cuda/pyproject.toml deployment/cuda/uv.lock ./
RUN uv sync --frozen --no-dev
COPY deployment/cuda-paddle/pyproject.toml deployment/cuda-paddle/uv.lock /paddle/
# uv divides its connect timeout across CDN addresses; Paddle can return dozens.
# Keep the read timeout above the connect timeout so uv does not cap it at 30s.
RUN UV_HTTP_CONNECT_TIMEOUT=120 UV_HTTP_TIMEOUT=180 UV_PROJECT_ENVIRONMENT=/app/.venv-paddle \
    uv sync --project /paddle --frozen --no-dev
COPY deployment/teleocr/pyproject.toml deployment/teleocr/uv.lock /tele/
RUN UV_PROJECT_ENVIRONMENT=/app/.venv-tele uv sync --project /tele --frozen --no-dev \
    && echo /app/.venv/lib/python3.12/site-packages > /app/.venv-tele/lib/python3.12/site-packages/parser-native.pth

FROM python:3.12-slim-trixie@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea AS dependencies-runner
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --group parser-runner && mkdir -p /app/.venv-paddle /app/.venv-tele

FROM dependencies-${PARSER_FLAVOR} AS dependencies

FROM python:3.12-slim-trixie@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea AS runtime
ARG SOURCE_COMMIT=uncommitted
ARG PARSER_FLAVOR
LABEL org.opencontainers.image.title="PDF parser without model weights" org.opencontainers.image.revision=$SOURCE_COMMIT
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app/src HOME=/tmp \
    DOCLING_ARTIFACTS_PATH=/opt/docling/models HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
    PARSER_INPUTS=/inputs PARSER_OUTPUTS=/outputs OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 TOKENIZERS_PARALLELISM=false \
    PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True PADDLE_PDX_DISABLE_DEVICE_FALLBACK=True \
    PADDLE_PDX_LOCAL_FONT_FILE_PATH=/opt/docling/models/RapidOcr/resources/fonts/FZYTK.TTF
WORKDIR /app
RUN apt-get update && apt-get upgrade -y \
    && if [ "$PARSER_FLAVOR" = runner ]; then apt-get install -y --no-install-recommends libgomp1; else apt-get install -y --no-install-recommends libgomp1 libgl1 libglib2.0-0; fi \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 library && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /tmp library \
    && mkdir -p /app/release && dpkg-query -W -f='${Package}\t${Version}\n' > /app/release/system-packages.tsv
COPY --from=dependencies /app/.venv /app/.venv
COPY --from=dependencies /app/.venv-paddle /app/.venv-paddle
COPY --from=dependencies /app/.venv-tele /app/.venv-tele
RUN /usr/local/bin/python -m pip uninstall --yes pip && /usr/local/bin/python -c "import shutil; shutil.rmtree('/usr/local/lib/python3.12/ensurepip')"
COPY src/packages/paths.py /app/src/packages/paths.py
COPY src/packages/ir/ /app/src/packages/ir/
COPY src/packages/parsers/ /app/src/packages/parsers/
COPY src/packages/local_models/ /app/src/packages/local_models/
COPY src/packages/metadata/discovery.py /app/src/packages/metadata/discovery.py
COPY src/packages/quality/ /app/src/packages/quality/
COPY src/packages/domain/workflow.py /app/src/packages/domain/workflow.py
COPY src/workers/parser/ /app/src/workers/parser/
COPY src/tools/export_parser_model.py /app/src/tools/export_parser_model.py
COPY res/schemas/ /app/res/schemas/
COPY deployment/parser-models.lock.json /app/deployment/parser-models.lock.json
COPY deployment/parser-vlm-models.lock.json /app/deployment/parser-vlm-models.lock.json
COPY pyproject.toml uv.lock /app/
COPY deployment/cuda/ /app/deployment/cuda/
COPY deployment/cuda-paddle/ /app/deployment/cuda-paddle/
COPY deployment/teleocr/ /app/deployment/teleocr/
RUN python -c "from importlib.metadata import distributions; import json; from pathlib import Path; Path('/app/release/python-packages.json').write_text(json.dumps(sorted([{'name': d.metadata['Name'], 'version': d.version, 'license': d.metadata.get('License-Expression') or d.metadata.get('License', 'UNKNOWN')} for d in distributions()], key=lambda x:x['name']), indent=2))"
RUN if [ -x /app/.venv-paddle/bin/python ]; then /app/.venv-paddle/bin/python -c "from importlib.metadata import distributions; import json; from pathlib import Path; Path('/app/release/python-packages-paddle.json').write_text(json.dumps(sorted([{'name': d.metadata['Name'], 'version': d.version} for d in distributions()], key=lambda x:x['name']), indent=2))"; fi
RUN if [ -x /app/.venv-tele/bin/python ]; then /app/.venv-tele/bin/python -c "from importlib.metadata import distributions; import json; from pathlib import Path; rows = {d.metadata['Name'].lower(): {'name': d.metadata['Name'], 'version': d.version} for d in reversed(list(distributions()))}; Path('/app/release/python-packages-teleocr.json').write_text(json.dumps(sorted(rows.values(), key=lambda x:x['name']), indent=2))"; fi
ENV PARSER_IMAGE_FLAVOR=$PARSER_FLAVOR
LABEL dev.bilingual-library.parser-flavor=$PARSER_FLAVOR
ARG SOURCE_TREE_SHA256=unrecorded
LABEL dev.bilingual-library.source-tree-sha256=$SOURCE_TREE_SHA256
USER 10001:10001
CMD ["python", "-m", "workers.parser.main"]
