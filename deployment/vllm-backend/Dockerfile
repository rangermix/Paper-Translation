FROM docker/model-runner@sha256:eaa0654180a88d6ebb6524f6f339e6a9cb32ae0f2441a5cc14a1573bc25e201d AS environment
USER root
RUN rm -rf /opt/vllm-env && mkdir /opt/vllm-env && chown modelrunner:modelrunner /opt/vllm-env
USER modelrunner
COPY --chown=modelrunner:modelrunner requirements.lock /tmp/requirements.lock
RUN --mount=type=cache,target=/home/modelrunner/.cache/uv,mode=0777 /home/modelrunner/.local/bin/uv venv --python 3.12 /opt/vllm-env \
    && /home/modelrunner/.local/bin/uv pip sync --python /opt/vllm-env/bin/python --require-hashes --torch-backend cu130 /tmp/requirements.lock \
    && /home/modelrunner/.local/bin/uv pip check --python /opt/vllm-env/bin/python
RUN /opt/vllm-env/bin/python -c "import torch, vllm; assert torch.version.cuda == '13.0'; assert vllm.__version__.split('+')[0] == '0.19.1'; print(vllm.__version__)" > /opt/vllm-env/version

# Do not inherit DMR's reserved com.docker.desktop.service image label: Docker
# Desktop hides containers carrying that key from Compose's container discovery.
FROM nvidia/cuda@sha256:73a15b1c6f93f5a3b05e453f5e6c13dd73418493d92222648e23ae597a69eac1
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       python3.12 python3.12-venv python3.12-dev build-essential \
       curl ca-certificates libnuma1 libglib2.0-0t64 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 995 modelrunner \
    && useradd --system --uid 995 --gid modelrunner --groups video \
       --create-home --home-dir /home/modelrunner modelrunner \
    && mkdir -p /var/run/model-runner /models /app \
    && chown modelrunner:modelrunner /var/run/model-runner /models /app
COPY --from=environment /opt/vllm-env /opt/vllm-env
COPY --from=environment --chown=modelrunner:modelrunner /app /app
COPY --chown=modelrunner:modelrunner startup.py /app/vllm-cuda-startup.py
COPY --chown=modelrunner:modelrunner start.sh /app/vllm-cuda-start.sh
# PyTorch wheels carry a consistent CUDA library set. Prepending the system
# toolkit here mixes its nvJitLink with wheel cuBLAS and breaks BF16/FP16 GEMM.
ENV MODEL_RUNNER_SOCK=/var/run/model-runner/model-runner.sock \
    MODEL_RUNNER_PORT=12434 \
    LLAMA_SERVER_PATH=/app \
    LLAMA_ARG_HOST=0.0.0.0 \
    LD_LIBRARY_PATH=/app:/usr/local/nvidia/lib:/usr/local/nvidia/lib64 \
    HOME=/home/modelrunner \
    MODELS_PATH=/models
WORKDIR /app
USER modelrunner
EXPOSE 12434
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -fsS "http://localhost:${MODEL_RUNNER_PORT}/engines/status" || exit 1
ENTRYPOINT ["/bin/sh", "/app/vllm-cuda-start.sh"]
LABEL io.paper-translation.backend="vllm-cuda" io.paper-translation.vllm-version="0.19.1"
