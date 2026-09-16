"""Defaults for this Docker-managed backend on the 16 GiB M4 host."""
import os

# DMR 1.2's Metal adapter ignores structured gpu-memory-utilization settings.
# Apply the native backend setting before vLLM/MLX imports and child startup.
os.environ.setdefault('VLLM_METAL_MEMORY_FRACTION', '0.25')
os.environ.setdefault('HF_HUB_OFFLINE', '1')
os.environ.setdefault('TRANSFORMERS_OFFLINE', '1')
os.environ.setdefault('HF_HUB_DISABLE_TELEMETRY', '1')
os.environ.setdefault('VLLM_NO_USAGE_STATS', '1')
