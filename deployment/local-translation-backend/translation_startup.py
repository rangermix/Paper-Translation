"""Allow per-model memory settings only for the packaged translation catalog."""
import json
import os
from pathlib import Path
import sys

# Executed before vLLM/MLX import. Children inherit this scoped environment.
known = set(json.loads(Path(__file__).with_name('translation_model_ids.json').read_text()))
if '--served-model-name' in sys.argv and '--gpu-memory-utilization' in sys.argv:
    names = []
    for value in sys.argv[sys.argv.index('--served-model-name') + 1:]:
        if value.startswith('--'):
            break
        names.append(value)
    if known.intersection(names):
        os.environ['VLLM_METAL_MEMORY_FRACTION'] = 'auto'


def bounded_cache_budget(model_name, max_length, block_size, bytes_per_block, available):
    """Only these single-request translation models need one context plus a null block."""
    names = [model_name] if isinstance(model_name, str) else model_name or []
    if known.intersection(names):
        return min(available, ((max_length + block_size - 1) // block_size + 1) * bytes_per_block)
    return available
