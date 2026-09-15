"""Bound this Docker-managed backend's Paddle and translation memory settings."""
import json
import os
from pathlib import Path
import re
import sys


def _option(args, flag):
    # DMR appends runtime flags after its structured options; argparse uses last.
    for index in range(len(args) - 1, -1, -1):
        value = args[index]
        if value == flag and index + 1 < len(args):
            return index, args[index + 1], False
        if value.startswith(flag + '='):
            return index, value.split('=', 1)[1], True
    return None, None, False


def _needs_context_cap(value):
    value = value.strip()
    if value.lower() == 'auto' or value == '-1':
        return True
    match = re.fullmatch(r'(\d+(?:\.\d+)?)([kKmMgGtT])', value)
    if match:
        number, suffix = match.groups()
        if suffix.isupper() and '.' in number:
            return False  # Invalid vLLM argument; leave its validation intact.
        power = 'kmgt'.index(suffix.lower()) + 1
        return float(number) * (1024 if suffix.isupper() else 1000) ** power > 8192
    try:
        return int(value) > 8192
    except ValueError:
        return False


def bound_paddle_context(args):
    """Keep Compose's 8192-token Paddle limit even after DMR drops its config.

    DMR unload removes runtime settings; reconfiguring eagerly reloads the
    retired model. Apply the cap only when this Paddle runner actually starts,
    before vLLM validates its KV cache. Smaller explicit limits are preserved.
    """
    _, model, _ = _option(args, '--model')
    if not model:
        return
    try:
        config = json.loads((Path(model) / 'config.json').read_text())
    except (OSError, ValueError):
        return  # vLLM retains responsibility for invalid/missing model files.
    if not isinstance(config, dict) or config.get('model_type') != 'paddleocr_vl' or config.get('architectures') != ['PaddleOCRVLForConditionalGeneration']:
        return
    index, limit, equals = _option(args, '--max-model-len')
    if limit is None:
        args.extend(['--max-model-len', '8192'])
    elif _needs_context_cap(limit):
        if equals:
            args[index] = '--max-model-len=8192'
        else:
            args[index + 1] = '8192'


bound_paddle_context(sys.argv)

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
