#!/bin/sh
set -eu
/opt/vllm-env/bin/python /app/vllm-cuda-startup.py
/opt/vllm-env/bin/python /app/resources.py &
exec /app/model-runner
