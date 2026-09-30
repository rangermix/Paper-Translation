#!/bin/sh
set -eu
/opt/vllm-env/bin/python /app/vllm-cuda-startup.py
exec /app/model-runner
