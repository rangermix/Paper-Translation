FROM docker/model-runner@sha256:eaa0654180a88d6ebb6524f6f339e6a9cb32ae0f2441a5cc14a1573bc25e201d
USER root
RUN rm -rf /opt/vllm-env && mkdir /opt/vllm-env && chown modelrunner:modelrunner /opt/vllm-env
USER modelrunner
COPY --chown=modelrunner:modelrunner requirements.lock /tmp/requirements.lock
RUN --mount=type=cache,target=/home/modelrunner/.cache/uv,mode=0777 /home/modelrunner/.local/bin/uv venv --python 3.12 /opt/vllm-env \
    && /home/modelrunner/.local/bin/uv pip sync --python /opt/vllm-env/bin/python --require-hashes --torch-backend cu130 /tmp/requirements.lock \
    && /home/modelrunner/.local/bin/uv pip check --python /opt/vllm-env/bin/python
RUN /opt/vllm-env/bin/python -c "import torch, vllm; assert torch.version.cuda == '13.0'; assert vllm.__version__.split('+')[0] == '0.19.1'; print(vllm.__version__)" > /opt/vllm-env/version
COPY --chown=modelrunner:modelrunner startup.py /app/vllm-cuda-startup.py
COPY --chown=modelrunner:modelrunner start.sh /app/vllm-cuda-start.sh
ENTRYPOINT ["/bin/sh", "/app/vllm-cuda-start.sh"]
LABEL io.paper-translation.backend="vllm-cuda" io.paper-translation.vllm-version="0.19.1"
